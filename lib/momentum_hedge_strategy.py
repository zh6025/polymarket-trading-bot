"""
Momentum-hedge strategy: fire when dominant side reaches threshold,
place main bet + Kelly-optimal hedge on the opposite side.
"""
import logging
import math
from typing import Dict, Any, List, Optional, Set

logger = logging.getLogger(__name__)


def _kelly_log_growth(p: float, main_price: float, hedge_ratio: float, fee: float = 0.02) -> float:
    """
    Expected log growth for a combined main+hedge bet.

    p         : estimated win probability for the main leg
    main_price: ask price for main leg (fraction of $1 payout)
    hedge_ratio: fraction of main notional allocated to hedge
    fee       : Polymarket fee rate (applied on profit)
    """
    win_pnl = (1.0 - main_price) * (1.0 - fee) - hedge_ratio * main_price
    loss_pnl = -main_price + hedge_ratio * (1.0 - main_price) * (1.0 - fee)
    p_win = max(1e-9, min(1 - 1e-9, p))
    p_loss = 1.0 - p_win
    if win_pnl <= -1 or loss_pnl <= -1:
        return -float("inf")
    return p_win * math.log(1 + win_pnl) + p_loss * math.log(1 + loss_pnl)


class MomentumHedgeStrategy:
    """
    One-shot momentum hedge strategy per market.

    check_trigger()            → True when dominant side >= threshold
    calculate_optimal_hedge_ratio() → grid search Kelly-optimal r ∈ [0.05, 0.50]
    estimate_win_rate()        → linear model W = clip(0.5 + (P-0.5)*slope, 0.55, 0.95)
    generate_orders()          → [main_order, hedge_order]
    """

    def __init__(
        self,
        trigger_threshold: float = 0.70,
        total_bet_size: float = 4.0,
        use_dynamic_ratio: bool = True,
        fixed_hedge_ratio: float = 0.33,
        win_rate_slope: float = 1.0,
        max_trigger_price: float = 0.85,
        fee_rate: float = 0.02,
    ):
        self.trigger_threshold = trigger_threshold
        self.total_bet_size = total_bet_size
        self.use_dynamic_ratio = use_dynamic_ratio
        self.fixed_hedge_ratio = fixed_hedge_ratio
        self.win_rate_slope = win_rate_slope
        self.max_trigger_price = max_trigger_price
        self.fee_rate = fee_rate
        self.bet_placed_markets: Set[str] = set()

    def check_trigger(self, up_price: float, down_price: float) -> bool:
        """Return True when the dominant side price >= trigger_threshold."""
        dominant = max(up_price, down_price)
        return dominant >= self.trigger_threshold

    def estimate_win_rate(self, price: float) -> float:
        """Linear win-rate model: W = clip(0.5 + (P-0.5)*slope, 0.55, 0.95)."""
        w = 0.5 + (price - 0.5) * self.win_rate_slope
        return max(0.55, min(0.95, w))

    def calculate_optimal_hedge_ratio(self, main_price: float, win_prob: float) -> float:
        """Grid-search Kelly-optimal hedge ratio r ∈ [0.05, 0.50]."""
        best_r, best_g = self.fixed_hedge_ratio, -float("inf")
        steps = 46  # 0.05 to 0.50 in 0.01 steps
        for i in range(steps):
            r = 0.05 + i * 0.01
            g = _kelly_log_growth(win_prob, main_price, r, self.fee_rate)
            if g > best_g:
                best_g, best_r = g, r
        return best_r

    def generate_orders(
        self,
        market_slug: str,
        up_price: float,
        down_price: float,
        up_token_id: str,
        down_token_id: str,
    ) -> List[Dict[str, Any]]:
        """
        Returns [hedge_order, main_order] or [] if already bet or trigger not met.

        **IMPORTANT — execution order**: the hedge order is always returned first.
        The caller MUST place the hedge order before the main order to ensure
        downside protection is in place before committing the larger main leg.
        This prevents the scenario where the main bet is placed but the hedge
        fill is delayed or rejected.
        """
        if market_slug in self.bet_placed_markets:
            logger.debug(f"Already bet on {market_slug}, skipping.")
            return []

        if not self.check_trigger(up_price, down_price):
            return []

        # Determine main/hedge sides
        if up_price >= down_price:
            main_price, main_outcome, main_token = up_price, "UP", up_token_id
            hedge_price, hedge_outcome, hedge_token = down_price, "DOWN", down_token_id
        else:
            main_price, main_outcome, main_token = down_price, "DOWN", down_token_id
            hedge_price, hedge_outcome, hedge_token = up_price, "UP", up_token_id

        if main_price > self.max_trigger_price:
            logger.info(f"Main price {main_price:.3f} > max trigger {self.max_trigger_price}, skip.")
            return []

        win_prob = self.estimate_win_rate(main_price)
        if self.use_dynamic_ratio:
            r = self.calculate_optimal_hedge_ratio(main_price, win_prob)
        else:
            r = self.fixed_hedge_ratio

        main_notional = self.total_bet_size / (1.0 + r)
        hedge_notional = main_notional * r

        main_order = {
            "outcome": main_outcome,
            "token_id": main_token,
            "side": "BUY",
            "price": main_price,
            "size": round(main_notional, 4),
            "role": "main",
        }
        hedge_order = {
            "outcome": hedge_outcome,
            "token_id": hedge_token,
            "side": "BUY",
            "price": hedge_price,
            "size": round(hedge_notional, 4),
            "role": "hedge",
        }

        self.bet_placed_markets.add(market_slug)
        logger.info(
            f"MomentumHedge {market_slug}: main={main_outcome}@{main_price:.3f}"
            f" size={main_notional:.2f}, hedge={hedge_outcome}@{hedge_price:.3f}"
            f" size={hedge_notional:.2f} (r={r:.2f})"
        )
        # Return hedge first so caller places it first
        return [hedge_order, main_order]
