"""
Production trade decision layer for the 5-minute Bitcoin up/down strategy.

Evaluates market conditions and returns a structured decision:
  SKIP                  – do not enter any position
  ENTER_MAIN_ONLY       – enter only the main (directional) leg
  ENTER_MAIN_AND_HEDGE  – enter both main and a cheap hedge leg
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Decision types
# ---------------------------------------------------------------------------

class Decision(str, Enum):
    SKIP = "SKIP"
    ENTER_MAIN_ONLY = "ENTER_MAIN_ONLY"
    ENTER_MAIN_AND_HEDGE = "ENTER_MAIN_AND_HEDGE"


@dataclass
class TradeDecision:
    decision: Decision
    reason: str
    hedge_ratio: float = 0.0
    main_size: float = 0.0
    hedge_size: float = 0.0
    metadata: dict = field(default_factory=dict)

    def __str__(self) -> str:
        return (
            f"Decision={self.decision.value} "
            f"reason={self.reason} "
            f"hedge_ratio={self.hedge_ratio:.3f} "
            f"main_size={self.main_size:.2f} "
            f"hedge_size={self.hedge_size:.2f}"
        )


# ---------------------------------------------------------------------------
# Hedge-ratio computation
# ---------------------------------------------------------------------------

# Coefficients for the k-factor (win-probability discount)
_K_TABLE = [
    (0.70, 0.45),
    (0.65, 0.60),
    (0.60, 0.75),
    (0.00, 0.90),
]

# Coefficients for the m-factor (main-price adjustment)
_M_TABLE = [
    (0.62, 0.80),
    (0.58, 0.90),
    (0.00, 1.00),
]

_MAX_HEDGE_RATIO = 0.35
_HEDGE_PRICE_HARD_MAX = 0.25


def compute_hedge_ratio(
    main_price: float,
    hedge_price: float,
    win_prob: float,
    *,
    hedge_price_hard_max: float = _HEDGE_PRICE_HARD_MAX,
    max_hedge_ratio: float = _MAX_HEDGE_RATIO,
) -> float:
    """
    Compute hedge_ratio = H / M based on main_price, hedge_price, and win_prob.

    Formula:
        r_be  = hedge_price / (1 - hedge_price)   # break-even ratio
        k     = discount factor derived from win_prob
        m     = adjustment factor derived from main_price
        ratio = clip(r_be * k * m, 0, max_hedge_ratio)

    Returns 0.0 if hedge_price > hedge_price_hard_max.
    """
    if hedge_price <= 0 or hedge_price >= 1:
        return 0.0
    if hedge_price > hedge_price_hard_max:
        return 0.0

    r_be = hedge_price / (1.0 - hedge_price)

    k = 0.90
    for threshold, coeff in _K_TABLE:
        if win_prob >= threshold:
            k = coeff
            break

    m = 1.00
    for threshold, coeff in _M_TABLE:
        if main_price > threshold:
            m = coeff
            break

    ratio = r_be * k * m
    return float(max(0.0, min(max_hedge_ratio, ratio)))


# ---------------------------------------------------------------------------
# Main decision function
# ---------------------------------------------------------------------------

def make_trade_decision(
    *,
    main_price: float,
    hedge_price: float,
    win_prob: float,
    remaining_sec: float,
    main_bet_size: float,
    # Time filters
    hard_stop_new_entry_sec: float = 30.0,
    min_secs_main_entry: float = 90.0,
    min_secs_hedge_entry: float = 60.0,
    # Price limits
    main_max_price: float = 0.66,
    main_min_price: float = 0.20,
    hedge_max_price: float = 0.25,
    hedge_min_price: float = 0.03,
    # Market quality thresholds
    main_spread: Optional[float] = None,
    hedge_spread: Optional[float] = None,
    main_top_book_depth: Optional[float] = None,
    hedge_top_book_depth: Optional[float] = None,
    main_max_spread: float = 0.03,
    hedge_max_spread: float = 0.02,
    main_min_depth: float = 10.0,
    hedge_min_depth: float = 5.0,
    # Feature flags
    enable_hedge: bool = True,
    hedge_price_hard_max: float = _HEDGE_PRICE_HARD_MAX,
) -> TradeDecision:
    """
    Evaluate market conditions and return a structured trade decision.

    Parameters
    ----------
    main_price : float
        Ask price of the main (directional) leg.
    hedge_price : float
        Ask price of the hedge (opposite) leg.
    win_prob : float
        Estimated probability that the main leg wins (0.0–1.0).
    remaining_sec : float
        Seconds until market settlement.
    main_bet_size : float
        Notional USDC amount for the main leg.
    *
    All keyword-only parameters control entry thresholds and are documented
    in the parameter table (see README / config defaults).

    Returns
    -------
    TradeDecision
    """
    meta: dict = dict(
        main_price=main_price,
        hedge_price=hedge_price,
        win_prob=win_prob,
        remaining_sec=remaining_sec,
        main_bet_size=main_bet_size,
    )

    # ------------------------------------------------------------------
    # 1. Hard stop – last N seconds: block ALL new entries
    # ------------------------------------------------------------------
    if remaining_sec < hard_stop_new_entry_sec:
        return TradeDecision(
            decision=Decision.SKIP,
            reason="remaining_below_hard_stop",
            metadata=dict(meta, hard_stop_new_entry_sec=hard_stop_new_entry_sec),
        )

    # ------------------------------------------------------------------
    # 2. Main entry time filter
    # ------------------------------------------------------------------
    if remaining_sec < min_secs_main_entry:
        return TradeDecision(
            decision=Decision.SKIP,
            reason="remaining_below_min_main_entry",
            metadata=dict(meta, min_secs_main_entry=min_secs_main_entry),
        )

    # ------------------------------------------------------------------
    # 3. Main price limits
    # ------------------------------------------------------------------
    if main_price > main_max_price:
        return TradeDecision(
            decision=Decision.SKIP,
            reason="main_price_above_max",
            metadata=dict(meta, main_max_price=main_max_price),
        )

    if main_price < main_min_price:
        return TradeDecision(
            decision=Decision.SKIP,
            reason="main_price_below_min",
            metadata=dict(meta, main_min_price=main_min_price),
        )

    # ------------------------------------------------------------------
    # 4. Main spread / depth checks
    # ------------------------------------------------------------------
    if main_spread is not None and main_spread > main_max_spread:
        return TradeDecision(
            decision=Decision.SKIP,
            reason="main_spread_too_wide",
            metadata=dict(meta, main_spread=main_spread, main_max_spread=main_max_spread),
        )

    if main_top_book_depth is not None and main_top_book_depth < main_min_depth:
        return TradeDecision(
            decision=Decision.SKIP,
            reason="main_depth_insufficient",
            metadata=dict(meta, main_top_book_depth=main_top_book_depth, main_min_depth=main_min_depth),
        )

    # ------------------------------------------------------------------
    # 5. Main leg passes – compute size
    # ------------------------------------------------------------------
    hedge_ratio = 0.0
    hedge_size = 0.0
    enter_hedge = False

    if enable_hedge:
        # 5a. Hedge time filter
        hedge_time_ok = remaining_sec >= min_secs_hedge_entry

        # 5b. Hedge price limits
        hedge_price_ok = (
            hedge_min_price <= hedge_price <= hedge_max_price
            and hedge_price <= hedge_price_hard_max
        )

        # 5c. Hedge spread / depth checks
        hedge_spread_ok = (
            hedge_spread is None or hedge_spread <= hedge_max_spread
        )
        hedge_depth_ok = (
            hedge_top_book_depth is None or hedge_top_book_depth >= hedge_min_depth
        )

        if hedge_time_ok and hedge_price_ok and hedge_spread_ok and hedge_depth_ok:
            hedge_ratio = compute_hedge_ratio(main_price, hedge_price, win_prob,
                                              hedge_price_hard_max=hedge_price_hard_max)
            if hedge_ratio > 0.0:
                enter_hedge = True
                hedge_size = round(main_bet_size * hedge_ratio, 2)

    meta["hedge_ratio"] = hedge_ratio

    if enter_hedge:
        return TradeDecision(
            decision=Decision.ENTER_MAIN_AND_HEDGE,
            reason="main_and_hedge_conditions_met",
            hedge_ratio=hedge_ratio,
            main_size=main_bet_size,
            hedge_size=hedge_size,
            metadata=meta,
        )
    else:
        return TradeDecision(
            decision=Decision.ENTER_MAIN_ONLY,
            reason="main_conditions_met_no_hedge",
            hedge_ratio=0.0,
            main_size=main_bet_size,
            hedge_size=0.0,
            metadata=meta,
        )


# ---------------------------------------------------------------------------
# Convenience log-line helper
# ---------------------------------------------------------------------------

def format_decision_log(
    market_slug: str,
    main_side: str,
    hedge_side: str,
    decision: TradeDecision,
) -> str:
    """Return a single structured log line for a trade decision."""
    d = decision
    m = d.metadata
    return (
        f"Decision={d.decision.value} "
        f"market={market_slug} "
        f"remaining={m.get('remaining_sec', '?'):.0f} "
        f"main_side={main_side} "
        f"main_price={m.get('main_price', '?'):.4f} "
        f"hedge_side={hedge_side} "
        f"hedge_price={m.get('hedge_price', '?'):.4f} "
        f"win_prob={m.get('win_prob', '?'):.2f} "
        f"hedge_ratio={d.hedge_ratio:.3f} "
        f"main_size={d.main_size:.2f} "
        f"hedge_size={d.hedge_size:.2f} "
        f"reason={d.reason}"
    )
