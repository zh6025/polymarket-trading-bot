"""
WindowStrategy: Multi-window single-direction trading strategy for BTC 5m markets.

Windows:
  Window 0 (optional, early momentum): ~260-275s remaining
  Mid-review checkpoint: ~115-125s remaining (stop-out window 0 positions)
  Window 1 (primary): ~90-95s remaining
  Window 2 (final): ~30-35s remaining
"""
import logging
from dataclasses import dataclass
from typing import Optional
from lib.session_state import SessionState
from lib.market_bias import Bias
from lib.market_data import OrderbookSnapshot

log = logging.getLogger(__name__)

# Window boundaries (seconds remaining)
WINDOW0_START = 275
WINDOW0_END = 260
MID_REVIEW_START = 125
MID_REVIEW_END = 115
WINDOW1_START = 95
WINDOW1_END = 90
WINDOW2_START = 35
WINDOW2_END = 30

# Sentinel value for "no active window" in WindowDecision.window
WINDOW_NONE = -99


@dataclass
class WindowDecision:
    action: str       # 'ENTER', 'EXIT', 'HOLD', 'SKIP', 'STOP_LOSS'
    direction: str    # 'UP', 'DOWN', or ''
    price: float
    size: float
    token_id: str
    reason: str
    window: int       # 0, 1, 2, -1 (mid-review), or -99 (no window)


def _no_action(reason: str, window: int = WINDOW_NONE) -> WindowDecision:
    return WindowDecision(action='SKIP', direction='', price=0.0, size=0.0,
                          token_id='', reason=reason, window=window)


def evaluate_window0(
    session: SessionState,
    secs_remaining: float,
    bias: Bias,
    ob_up: Optional[OrderbookSnapshot],
    ob_down: Optional[OrderbookSnapshot],
    bet_size: float,
    hard_cap_price: float = 0.85,
    min_confidence: float = 0.70,
    max_spread: float = 0.04,
    min_depth: float = 30.0,
    window0_enabled: bool = False,
) -> WindowDecision:
    """Window 0: Early momentum entry (disabled by default)"""
    if not window0_enabled:
        return _no_action("window0_disabled", 0)
    if session.window0_processed:
        return _no_action("window0_already_processed", 0)
    if not (WINDOW0_END <= secs_remaining <= WINDOW0_START):
        return _no_action(f"not_in_window0 ({secs_remaining:.0f}s)", 0)

    if bias == Bias.NEUTRAL:
        return _no_action("window0_bias_neutral", 0)

    direction = bias.value
    ob = ob_up if direction == 'UP' else ob_down
    if ob is None or not ob.is_valid:
        return _no_action("window0_no_orderbook", 0)

    if ob.price > hard_cap_price:
        return _no_action(f"window0_price_above_cap {ob.price:.3f}>{hard_cap_price}", 0)

    if ob.price < min_confidence:
        return _no_action(f"window0_price_too_low {ob.price:.3f}<{min_confidence}", 0)

    if ob.spread is not None and ob.spread > max_spread:
        return _no_action(f"window0_spread_too_wide {ob.spread:.3f}", 0)

    if (ob.bid_depth + ob.ask_depth) < min_depth:
        return _no_action("window0_depth_insufficient", 0)

    # Window 0 uses smaller size (50% of normal)
    return WindowDecision(
        action='ENTER',
        direction=direction,
        price=ob.price,
        size=bet_size * 0.5,
        token_id=ob.token_id,
        reason=f"window0_entry bias={bias.value}",
        window=0,
    )


def evaluate_mid_review(
    session: SessionState,
    secs_remaining: float,
    bias: Bias,
    ob_up: Optional[OrderbookSnapshot],
    ob_down: Optional[OrderbookSnapshot],
) -> WindowDecision:
    """Mid-review checkpoint: Stop out window 0 positions if direction flipped"""
    if session.mid_review_processed:
        return _no_action("mid_review_already_processed", -1)
    if not (MID_REVIEW_END <= secs_remaining <= MID_REVIEW_START):
        return _no_action(f"not_in_mid_review ({secs_remaining:.0f}s)", -1)

    if not session.has_position:
        return _no_action("mid_review_no_position", -1)

    pos_dir = session.position_direction
    if bias != Bias.NEUTRAL and bias.value != pos_dir:
        ob = ob_up if pos_dir == 'UP' else ob_down
        price = ob.price if (ob and ob.is_valid) else session.position_entry_price
        return WindowDecision(
            action='STOP_LOSS',
            direction=pos_dir,
            price=price,
            size=session.position_size,
            token_id=session.position_token_id,
            reason=f"mid_review_direction_flip: held={pos_dir} bias={bias.value}",
            window=-1,
        )

    return _no_action("mid_review_no_flip", -1)


def evaluate_window1(
    session: SessionState,
    secs_remaining: float,
    bias: Bias,
    ob_up: Optional[OrderbookSnapshot],
    ob_down: Optional[OrderbookSnapshot],
    bet_size: float,
    hard_cap_price: float = 0.85,
    min_confidence: float = 0.55,
    max_spread: float = 0.05,
    min_depth: float = 50.0,
) -> WindowDecision:
    """Window 1: Primary entry window (~90-95s remaining)"""
    if session.window1_processed:
        return _no_action("window1_already_processed", 1)
    if not (WINDOW1_END <= secs_remaining <= WINDOW1_START):
        return _no_action(f"not_in_window1 ({secs_remaining:.0f}s)", 1)

    if session.has_position:
        return _no_action("window1_already_holding", 1)

    if bias == Bias.NEUTRAL:
        return _no_action("window1_bias_neutral", 1)

    direction = bias.value
    ob = ob_up if direction == 'UP' else ob_down
    if ob is None or not ob.is_valid:
        return _no_action("window1_no_orderbook", 1)

    if ob.price > hard_cap_price:
        return _no_action(f"window1_price_above_cap {ob.price:.3f}>{hard_cap_price}", 1)

    if ob.price < min_confidence:
        return _no_action(f"window1_price_too_low {ob.price:.3f}", 1)

    if ob.spread is not None and ob.spread > max_spread:
        return _no_action(f"window1_spread_too_wide {ob.spread:.3f}", 1)

    if (ob.bid_depth + ob.ask_depth) < min_depth:
        return _no_action("window1_depth_insufficient", 1)

    return WindowDecision(
        action='ENTER',
        direction=direction,
        price=ob.price,
        size=bet_size,
        token_id=ob.token_id,
        reason=f"window1_entry bias={bias.value}",
        window=1,
    )


def evaluate_window2(
    session: SessionState,
    secs_remaining: float,
    bias: Bias,
    ob_up: Optional[OrderbookSnapshot],
    ob_down: Optional[OrderbookSnapshot],
    bet_size: float,
    hard_cap_price: float = 0.85,
    late_entry_min_price: float = 0.65,
    max_spread: float = 0.04,
    min_depth: float = 50.0,
) -> WindowDecision:
    """Window 2: Final window (~30-35s remaining)
    - If holding and direction flipped: stop-loss
    - If not holding and conditions very strong: late entry
    """
    if session.window2_processed:
        return _no_action("window2_already_processed", 2)
    if not (WINDOW2_END <= secs_remaining <= WINDOW2_START):
        return _no_action(f"not_in_window2 ({secs_remaining:.0f}s)", 2)

    # Stop-loss check first if holding
    if session.has_position:
        pos_dir = session.position_direction
        if bias != Bias.NEUTRAL and bias.value != pos_dir:
            ob = ob_up if pos_dir == 'UP' else ob_down
            price = ob.price if (ob and ob.is_valid) else session.position_entry_price
            return WindowDecision(
                action='STOP_LOSS',
                direction=pos_dir,
                price=price,
                size=session.position_size,
                token_id=session.position_token_id,
                reason=f"window2_stop_loss: held={pos_dir} bias={bias.value}",
                window=2,
            )
        return _no_action("window2_holding_no_flip", 2)

    # Late entry only if very strong signal
    if bias == Bias.NEUTRAL:
        return _no_action("window2_no_position_bias_neutral", 2)

    direction = bias.value
    ob = ob_up if direction == 'UP' else ob_down
    if ob is None or not ob.is_valid:
        return _no_action("window2_no_orderbook", 2)

    if ob.price > hard_cap_price:
        return _no_action(f"window2_price_above_cap {ob.price:.3f}", 2)

    if ob.price < late_entry_min_price:
        return _no_action(f"window2_price_not_strong_enough {ob.price:.3f}<{late_entry_min_price}", 2)

    if ob.spread is not None and ob.spread > max_spread:
        return _no_action(f"window2_spread_too_wide {ob.spread:.3f}", 2)

    if (ob.bid_depth + ob.ask_depth) < min_depth:
        return _no_action("window2_depth_insufficient", 2)

    return WindowDecision(
        action='ENTER',
        direction=direction,
        price=ob.price,
        size=bet_size,
        token_id=ob.token_id,
        reason=f"window2_late_entry bias={bias.value}",
        window=2,
    )


def run_window_strategy(
    session: SessionState,
    secs_remaining: float,
    bias: Bias,
    ob_up: Optional[OrderbookSnapshot],
    ob_down: Optional[OrderbookSnapshot],
    bet_size: float,
    hard_cap_price: float = 0.85,
    window0_enabled: bool = False,
    min_confidence_w0: float = 0.70,
    min_confidence_w1: float = 0.55,
    late_entry_min_price: float = 0.65,
    max_spread: float = 0.05,
    min_depth: float = 50.0,
    recent_volatility: Optional[float] = None,
    max_recent_volatility: float = 0.20,
) -> WindowDecision:
    """
    Main entry point: evaluate all windows in order and return first applicable action.

    Args:
        session: Current session state
        secs_remaining: Seconds until market close
        bias: Current market bias
        ob_up: Orderbook snapshot for UP token
        ob_down: Orderbook snapshot for DOWN token
        bet_size: Bet size in USDC
        hard_cap_price: Never buy above this price
        window0_enabled: Feature flag for window 0
        recent_volatility: Recent price change fraction (for safety check)
        max_recent_volatility: If recent volatility exceeds this, skip
    """
    if recent_volatility is not None and recent_volatility > max_recent_volatility:
        log.warning(f"Volatility filter triggered: {recent_volatility:.3f} > {max_recent_volatility}")
        return _no_action(f"volatility_filter {recent_volatility:.3f}", WINDOW_NONE)

    # Window 0
    if not session.window0_processed and WINDOW0_END <= secs_remaining <= WINDOW0_START:
        result = evaluate_window0(
            session=session, secs_remaining=secs_remaining, bias=bias,
            ob_up=ob_up, ob_down=ob_down, bet_size=bet_size,
            hard_cap_price=hard_cap_price, min_confidence=min_confidence_w0,
            max_spread=max_spread, min_depth=min_depth, window0_enabled=window0_enabled,
        )
        session.window0_processed = True
        if result.action != 'SKIP':
            return result

    # Mid-review checkpoint
    if not session.mid_review_processed and MID_REVIEW_END <= secs_remaining <= MID_REVIEW_START:
        result = evaluate_mid_review(
            session=session, secs_remaining=secs_remaining, bias=bias,
            ob_up=ob_up, ob_down=ob_down,
        )
        session.mid_review_processed = True
        if result.action != 'SKIP':
            return result

    # Window 1
    if not session.window1_processed and WINDOW1_END <= secs_remaining <= WINDOW1_START:
        result = evaluate_window1(
            session=session, secs_remaining=secs_remaining, bias=bias,
            ob_up=ob_up, ob_down=ob_down, bet_size=bet_size,
            hard_cap_price=hard_cap_price, min_confidence=min_confidence_w1,
            max_spread=max_spread, min_depth=min_depth,
        )
        session.window1_processed = True
        if result.action != 'SKIP':
            return result

    # Window 2
    if not session.window2_processed and WINDOW2_END <= secs_remaining <= WINDOW2_START:
        result = evaluate_window2(
            session=session, secs_remaining=secs_remaining, bias=bias,
            ob_up=ob_up, ob_down=ob_down, bet_size=bet_size,
            hard_cap_price=hard_cap_price, late_entry_min_price=late_entry_min_price,
            max_spread=max_spread, min_depth=min_depth,
        )
        session.window2_processed = True
        if result.action != 'SKIP':
            return result

    return _no_action("no_active_window", WINDOW_NONE)
