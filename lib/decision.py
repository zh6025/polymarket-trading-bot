"""
Decision layer: sequential gate evaluation for trade entry.
"""
import math
import logging
from typing import Tuple, Dict, Any, Optional

logger = logging.getLogger(__name__)

# Decision outcomes
SKIP = "SKIP"
ENTER_MAIN_ONLY = "ENTER_MAIN_ONLY"
ENTER_MAIN_AND_HEDGE = "ENTER_MAIN_AND_HEDGE"


def compute_hedge_ratio(main_price: float, hedge_price: float, win_prob: float) -> float:
    """
    Kelly-based hedge ratio capped at 0.35.

    The ratio r is chosen so the hedge covers the main leg loss:
        r = (main_price * win_prob) / ((1 - hedge_price) * (1 - win_prob))
    then clamped to [0.05, 0.35].

    The 0.35 upper cap prevents over-hedging which can erode expected value
    when win probability is high.  The 0.05 minimum ensures a token hedge
    is always present when the caller requests it.
    """
    denom = (1.0 - hedge_price) * max(1.0 - win_prob, 1e-6)
    if denom <= 0:
        return 0.05
    raw = (main_price * win_prob) / denom
    return max(0.05, min(0.35, raw))


def make_trade_decision(
    seconds_remaining: int,
    min_remaining_seconds: int,
    main_ask: float,
    main_max_price: float,
    hedge_ask: float,
    hedge_max_price: float,
    spread_pct: float,
    max_spread_pct: float,
    depth_ok: bool,
    hard_stop_secs: int = 30,
    enable_hedge: bool = False,
) -> Tuple[str, str]:
    """
    Sequential gate evaluation.

    Returns (decision, reason) where decision is one of SKIP / ENTER_MAIN_ONLY /
    ENTER_MAIN_AND_HEDGE.
    """
    # Gate 1: hard stop — too close to resolution
    if seconds_remaining <= hard_stop_secs:
        return SKIP, f"hard_stop: {seconds_remaining}s <= {hard_stop_secs}s"

    # Gate 2: minimum remaining window
    if seconds_remaining < min_remaining_seconds:
        return SKIP, f"min_remaining: {seconds_remaining}s < {min_remaining_seconds}s"

    # Gate 3: main price band
    if main_ask > main_max_price:
        return SKIP, f"main_price {main_ask:.3f} > max {main_max_price:.3f}"

    # Gate 4: spread
    if spread_pct > max_spread_pct:
        return SKIP, f"spread {spread_pct:.3f} > max {max_spread_pct:.3f}"

    # Gate 5: depth
    if not depth_ok:
        return SKIP, "insufficient_depth"

    # All main gates passed — decide hedge
    if enable_hedge and hedge_ask <= hedge_max_price:
        return ENTER_MAIN_AND_HEDGE, "all_gates_pass+hedge_ok"

    return ENTER_MAIN_ONLY, "all_gates_pass"


def format_decision_log(
    cycle: int,
    market_slug: str,
    decision: str,
    reason: str,
    main_ask: float,
    seconds_remaining: int,
    extra: Optional[Dict[str, Any]] = None,
) -> str:
    """Structured one-liner decision log."""
    parts = [
        f"cycle={cycle}",
        f"market={market_slug}",
        f"decision={decision}",
        f"reason={reason}",
        f"main_ask={main_ask:.4f}",
        f"secs_left={seconds_remaining}",
    ]
    if extra:
        for k, v in extra.items():
            parts.append(f"{k}={v}")
    return " | ".join(parts)
