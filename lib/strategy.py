import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Tuple, Optional

from lib.utils import round_to_tick, log_info

logger = logging.getLogger(__name__)

class GridStrategy:
    """Grid Trading Strategy"""
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize grid strategy with config"""
        self.config = config
        self.grid_levels = []
        self.orders = []
    
    def validate_config(self, tick_size: float, min_order_size: float):
        """Validate strategy configuration"""
        order_size = self.config.get('order_size', 5)
        grid_step = self.config.get('grid_step', 0.02)
        
        if order_size < min_order_size:
            raise ValueError(f"order_size ({order_size}) < min_order_size ({min_order_size})")
        
        # Check if grid_step is multiple of tick_size
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
        """Generate grid price levels"""
        levels = []
        
        # Lower levels
        for i in range(levels_each_side, 0, -1):
            price = round_to_tick(mid_price - grid_step * i, tick_size)
            if tick_size <= price <= 1 - tick_size:
                levels.append(price)
        
        # Center level
        levels.append(round_to_tick(mid_price, tick_size))
        
        # Upper levels
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
        """Generate order plan based on grid levels"""
        plan = []
        order_size = self.config.get('order_size', 5)
        
        # Up side orders
        for price in self.grid_levels:
            if price < up_mid:
                plan.append({
                    'side': 'BUY',
                    'outcome': 'Up',
                    'token_id': up_token,
                    'price': price,
                    'size': order_size
                })
            elif price > up_mid:
                plan.append({
                    'side': 'SELL',
                    'outcome': 'Up',
                    'token_id': up_token,
                    'price': price,
                    'size': order_size
                })
        
        # Down side orders
        if trade_both:
            for price in self.grid_levels:
                if price < down_mid:
                    plan.append({
                        'side': 'BUY',
                        'outcome': 'Down',
                        'token_id': down_token,
                        'price': price,
                        'size': order_size
                    })
                elif price > down_mid:
                    plan.append({
                        'side': 'SELL',
                        'outcome': 'Down',
                        'token_id': down_token,
                        'price': price,
                        'size': order_size
                    })
        
        self.orders = plan
        log_info(f"✅ Generated {len(plan)} orders")
        return plan
    
    def get_order_plan(self) -> List[Dict[str, Any]]:
        """Get sorted order plan"""
        return sorted(
            self.orders,
            key=lambda o: (o['outcome'], o['price'])
        )


@dataclass
class TradeDecision:
    decision: str                    # "TRADE" or "SKIP"
    decision_reason: str
    hedge_ratio: float = 0.0
    main_size: float = 0.0
    hedge_size: float = 0.0
    should_trade_hedge: bool = False
    skip_reasons: list = field(default_factory=list)


class ProductionDecisionStrategy:
    """
    Late-entry momentum + Kelly-hedge strategy for BTC 5m binary markets.

    Decides whether to enter a trade based on order-book imbalance, price
    positioning, timing within the 5-minute window, and risk parameters.
    Returns a TradeDecision describing what to do.
    """

    def __init__(self, config):
        self.config = config

    def decide(
        self,
        *,
        main_outcome: str,
        main_token_id: str,
        main_price: float,
        main_bid: float,
        main_ask: float,
        main_depth_usdc: float,
        hedge_outcome: str,
        hedge_token_id: str,
        hedge_price: float,
        hedge_bid: float,
        hedge_ask: float,
        hedge_depth_usdc: float,
        elapsed_sec: float,
        market_duration_sec: float = 300.0,
    ) -> TradeDecision:
        cfg = self.config
        skip_reasons = []

        # ── Timing guard ─────────────────────────────────────────────────────
        remaining = market_duration_sec - elapsed_sec
        if remaining < cfg.hard_stop_new_entry_sec:
            return TradeDecision(
                decision="SKIP",
                decision_reason=f"Too close to expiry ({remaining:.0f}s remaining)",
                skip_reasons=[f"remaining={remaining:.0f}s < hard_stop={cfg.hard_stop_new_entry_sec}s"],
            )

        # ── Price range guards ────────────────────────────────────────────────
        if not (cfg.min_main_price <= main_price <= cfg.max_main_price):
            skip_reasons.append(
                f"main_price={main_price:.4f} outside [{cfg.min_main_price},{cfg.max_main_price}]"
            )

        if not (cfg.min_hedge_price <= hedge_price <= cfg.max_hedge_price):
            skip_reasons.append(
                f"hedge_price={hedge_price:.4f} outside [{cfg.min_hedge_price},{cfg.max_hedge_price}]"
            )

        # ── Spread guards ─────────────────────────────────────────────────────
        main_spread = main_ask - main_bid
        if main_spread > cfg.max_main_spread:
            skip_reasons.append(f"main_spread={main_spread:.4f} > {cfg.max_main_spread}")

        hedge_spread = hedge_ask - hedge_bid
        if hedge_spread > cfg.max_hedge_spread:
            skip_reasons.append(f"hedge_spread={hedge_spread:.4f} > {cfg.max_hedge_spread}")

        # ── Depth guards ──────────────────────────────────────────────────────
        if main_depth_usdc < cfg.min_main_depth_usdc:
            skip_reasons.append(
                f"main_depth={main_depth_usdc:.1f} < {cfg.min_main_depth_usdc}"
            )

        if hedge_depth_usdc < cfg.min_hedge_depth_usdc:
            skip_reasons.append(
                f"hedge_depth={hedge_depth_usdc:.1f} < {cfg.min_hedge_depth_usdc}"
            )

        if skip_reasons:
            return TradeDecision(
                decision="SKIP",
                decision_reason="; ".join(skip_reasons),
                skip_reasons=skip_reasons,
            )

        # ── Kelly-optimal hedge sizing ────────────────────────────────────────
        win_prob = main_price          # treat mid-price as implied win probability
        if win_prob < cfg.min_win_prob:
            return TradeDecision(
                decision="SKIP",
                decision_reason=f"win_prob={win_prob:.4f} < min={cfg.min_win_prob}",
                skip_reasons=[f"win_prob={win_prob:.4f} < {cfg.min_win_prob}"],
            )

        # Kelly fraction for the main bet (simplified)
        kelly_f = (win_prob - (1 - win_prob)) / 1.0
        kelly_f = max(0.0, min(kelly_f, 1.0))

        main_size = round(cfg.min_order_size * max(1.0, kelly_f * 4), 2)
        main_size = min(main_size, cfg.max_position_size)

        # Hedge ratio: partial hedge proportional to uncertainty
        raw_hedge_ratio = 1.0 - win_prob
        hedge_ratio = max(
            cfg.min_meaningful_hedge_ratio,
            min(raw_hedge_ratio, cfg.max_hedge_ratio),
        )
        hedge_size = round(main_size * hedge_ratio, 2)
        should_trade_hedge = hedge_ratio >= cfg.min_meaningful_hedge_ratio

        logger.info(
            f"TRADE decision: main={main_outcome}@{main_price:.4f}x{main_size} "
            f"hedge={hedge_outcome}@{hedge_price:.4f}x{hedge_size} ratio={hedge_ratio:.3f}"
        )

        return TradeDecision(
            decision="TRADE",
            decision_reason=(
                f"win_prob={win_prob:.4f} kelly_f={kelly_f:.3f} "
                f"hedge_ratio={hedge_ratio:.3f}"
            ),
            hedge_ratio=hedge_ratio,
            main_size=main_size,
            hedge_size=hedge_size,
            should_trade_hedge=should_trade_hedge,
        )
