from dataclasses import dataclass
from typing import List, Dict, Any
from lib.utils import round_to_tick, log_info


@dataclass
class TradeDecision:
    decision: str
    decision_reason: str
    should_trade_main: bool
    should_trade_hedge: bool
    hedge_ratio: float
    main_size: float
    hedge_size: float
    skip_reasons: List[str]


class GridStrategy:
    """Grid Trading Strategy"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.grid_levels = []
        self.orders = []

    def validate_config(self, tick_size: float, min_order_size: float):
        order_size = self.config.get("order_size", 5)
        grid_step = self.config.get("grid_step", 0.02)

        if order_size < min_order_size:
            raise ValueError(f"order_size ({order_size}) < min_order_size ({min_order_size})")

        steps_in_ticks = round(grid_step / tick_size)
        step_in_ticks = steps_in_ticks * tick_size

        if abs(step_in_ticks - grid_step) > 1e-10:
            raise ValueError(f"grid_step ({grid_step}) is not multiple of tick_size ({tick_size})")

        log_info("✅ Strategy config validated")

    def generate_grid_levels(
        self,
        mid_price: float,
        tick_size: float,
        grid_step: float,
        levels_each_side: int
    ) -> List[float]:
        levels = []

        for i in range(levels_each_side, 0, -1):
            price = round_to_tick(mid_price - grid_step * i, tick_size)
            if tick_size <= price <= 1 - tick_size:
                levels.append(price)

        levels.append(round_to_tick(mid_price, tick_size))

        for i in range(1, levels_each_side + 1):
            price = round_to_tick(mid_price + grid_step * i, tick_size)
            if tick_size <= price <= 1 - tick_size:
                levels.append(price)

        self.grid_levels = levels
        log_info(f"✅ Generated {len(levels)} grid levels")
        return levels

    def generate_order_plan(
        self,
        up_mid: float,
        down_mid: float,
        up_token: str,
        down_token: str,
        trade_both: bool = True
    ) -> List[Dict[str, Any]]:
        plan = []
        order_size = self.config.get("order_size", 5)

        for price in self.grid_levels:
            if price < up_mid:
                plan.append({
                    "side": "BUY",
                    "outcome": "Up",
                    "token_id": up_token,
                    "price": price,
                    "size": order_size
                })
            elif price > up_mid:
                plan.append({
                    "side": "SELL",
                    "outcome": "Up",
                    "token_id": up_token,
                    "price": price,
                    "size": order_size
                })

        if trade_both:
            for price in self.grid_levels:
                if price < down_mid:
                    plan.append({
                        "side": "BUY",
                        "outcome": "Down",
                        "token_id": down_token,
                        "price": price,
                        "size": order_size
                    })
                elif price > down_mid:
                    plan.append({
                        "side": "SELL",
                        "outcome": "Down",
                        "token_id": down_token,
                        "price": price,
                        "size": order_size
                    })

        self.orders = plan
        log_info(f"✅ Generated {len(plan)} orders")
        return plan

    def get_order_plan(self) -> List[Dict[str, Any]]:
        return sorted(
            self.orders,
            key=lambda o: (o["outcome"], o["price"])
        )


class ProductionDecisionStrategy:
    def __init__(self, config: Any):
        self.config = config

    def _cfg(self, key: str, default: Any = None) -> Any:
        if isinstance(self.config, dict):
            return self.config.get(key, default)
        return getattr(self.config, key, default)

    def _clamp(self, value: float, low: float, high: float) -> float:
        return max(low, min(high, value))

    def calculate_hedge_ratio(
        self,
        main_price: float,
        hedge_price: float,
        win_prob: float,
    ) -> float:
        max_hedge_ratio = self._cfg("max_hedge_ratio", 0.33)

        r_be = hedge_price / (1.0 - hedge_price)

        if win_prob >= 0.70:
            k = 0.45
        elif win_prob >= 0.65:
            k = 0.60
        elif win_prob >= 0.60:
            k = 0.75
        else:
            k = 0.90

        if main_price <= 0.58:
            m = 1.00
        elif main_price <= 0.62:
            m = 0.90
        else:
            m = 0.80

        hedge_ratio = r_be * k * m
        return self._clamp(hedge_ratio, 0.0, max_hedge_ratio)

    def decide(
        self,
        main_price: float,
        hedge_price: float,
        win_prob: float,
        remaining_sec: int,
        main_spread: float,
        hedge_spread: float,
        main_depth_usdc: float,
        hedge_depth_usdc: float,
        main_size_usdc: float = 3.0,
    ) -> TradeDecision:
        skip_reasons: List[str] = []

        hard_stop_new_entry_sec = self._cfg("hard_stop_new_entry_sec", 30)
        min_secs_main_entry = self._cfg("min_secs_main_entry", 90)
        min_secs_hedge_entry = self._cfg("min_secs_hedge_entry", 60)

        min_main_price = self._cfg("min_main_price", 0.20)
        max_main_price = self._cfg("max_main_price", 0.66)
        min_hedge_price = self._cfg("min_hedge_price", 0.03)
        max_hedge_price = self._cfg("max_hedge_price", 0.25)

        max_main_spread = self._cfg("max_main_spread", 0.03)
        max_hedge_spread = self._cfg("max_hedge_spread", 0.02)

        min_main_depth_usdc = self._cfg("min_main_depth_usdc", 10.0)
        min_hedge_depth_usdc = self._cfg("min_hedge_depth_usdc", 5.0)

        min_win_prob = self._cfg("min_win_prob", 0.55)
        min_meaningful_hedge_ratio = self._cfg("min_meaningful_hedge_ratio", 0.05)

        if not (0 < main_price < 1):
            skip_reasons.append("invalid_main_price")
        if not (0 < hedge_price < 1):
            skip_reasons.append("invalid_hedge_price")
        if not (0 < win_prob < 1):
            skip_reasons.append("invalid_win_prob")
        if remaining_sec < 0:
            skip_reasons.append("invalid_remaining_sec")
        if main_spread < 0:
            skip_reasons.append("invalid_main_spread")
        if hedge_spread < 0:
            skip_reasons.append("invalid_hedge_spread")
        if main_depth_usdc < 0:
            skip_reasons.append("invalid_main_depth_usdc")
        if hedge_depth_usdc < 0:
            skip_reasons.append("invalid_hedge_depth_usdc")
        if main_size_usdc <= 0:
            skip_reasons.append("invalid_main_size_usdc")

        if skip_reasons:
            return TradeDecision(
                decision="SKIP",
                decision_reason="invalid_input",
                should_trade_main=False,
                should_trade_hedge=False,
                hedge_ratio=0.0,
                main_size=0.0,
                hedge_size=0.0,
                skip_reasons=skip_reasons,
            )

        if remaining_sec < hard_stop_new_entry_sec:
            return TradeDecision(
                decision="SKIP",
                decision_reason="remaining_below_hard_stop",
                should_trade_main=False,
                should_trade_hedge=False,
                hedge_ratio=0.0,
                main_size=0.0,
                hedge_size=0.0,
                skip_reasons=["remaining_below_hard_stop"],
            )

        should_trade_main = True
        should_trade_hedge = False
        hedge_ratio = 0.0

        if remaining_sec < min_secs_main_entry:
            should_trade_main = False
            skip_reasons.append("remaining_below_min_secs_main")

        if main_price < min_main_price:
            should_trade_main = False
            skip_reasons.append("main_price_below_min")

        if main_price > max_main_price:
            should_trade_main = False
            skip_reasons.append("main_price_above_max")

        if win_prob < min_win_prob:
            should_trade_main = False
            skip_reasons.append("win_prob_below_min")

        if main_spread > max_main_spread:
            should_trade_main = False
            skip_reasons.append("main_spread_above_max")

        if main_depth_usdc < min_main_depth_usdc:
            should_trade_main = False
            skip_reasons.append("main_depth_below_min")

        if not should_trade_main:
            return TradeDecision(
                decision="SKIP",
                decision_reason=skip_reasons[0] if skip_reasons else "main_not_allowed",
                should_trade_main=False,
                should_trade_hedge=False,
                hedge_ratio=0.0,
                main_size=0.0,
                hedge_size=0.0,
                skip_reasons=skip_reasons,
            )

        hedge_allowed = True

        if remaining_sec < min_secs_hedge_entry:
            hedge_allowed = False
            skip_reasons.append("remaining_below_min_secs_hedge")

        if hedge_price < min_hedge_price:
            hedge_allowed = False
            skip_reasons.append("hedge_price_below_min")

        if hedge_price > max_hedge_price:
            hedge_allowed = False
            skip_reasons.append("hedge_price_above_max")

        if hedge_spread > max_hedge_spread:
            hedge_allowed = False
            skip_reasons.append("hedge_spread_above_max")

        if hedge_depth_usdc < min_hedge_depth_usdc:
            hedge_allowed = False
            skip_reasons.append("hedge_depth_below_min")

        if hedge_allowed:
            hedge_ratio = self.calculate_hedge_ratio(
                main_price=main_price,
                hedge_price=hedge_price,
                win_prob=win_prob,
            )

            if hedge_ratio >= min_meaningful_hedge_ratio:
                should_trade_hedge = True
            else:
                hedge_ratio = 0.0
                skip_reasons.append("hedge_ratio_too_small")

        main_size = round(main_size_usdc, 2)
        hedge_size = round(main_size * hedge_ratio, 2) if should_trade_hedge else 0.0

        if should_trade_main and should_trade_hedge:
            decision = "ENTER_MAIN_AND_HEDGE"
            decision_reason = "main_and_hedge_allowed"
        else:
            decision = "ENTER_MAIN_ONLY"
            if "hedge_price_above_max" in skip_reasons:
                decision_reason = "hedge_too_expensive"
            elif "remaining_below_min_secs_hedge" in skip_reasons:
                decision_reason = "not_enough_time_for_hedge"
            elif "hedge_spread_above_max" in skip_reasons:
                decision_reason = "hedge_spread_too_wide"
            elif "hedge_depth_below_min" in skip_reasons:
                decision_reason = "hedge_depth_too_thin"
            elif "hedge_ratio_too_small" in skip_reasons:
                decision_reason = "hedge_not_meaningful"
            else:
                decision_reason = "main_allowed_hedge_not_allowed"

        log_info(
            f"Decision={decision} reason={decision_reason} "
            f"main_price={main_price:.4f} hedge_price={hedge_price:.4f} "
            f"win_prob={win_prob:.3f} remaining_sec={remaining_sec} "
            f"main_size={main_size:.2f} hedge_size={hedge_size:.2f} "
            f"hedge_ratio={hedge_ratio:.4f} skip_reasons={skip_reasons}"
        )

        return TradeDecision(
            decision=decision,
            decision_reason=decision_reason,
            should_trade_main=True,
            should_trade_hedge=should_trade_hedge,
            hedge_ratio=round(hedge_ratio, 4),
            main_size=main_size,
            hedge_size=hedge_size,
            skip_reasons=skip_reasons,
        )
