"""
decision.py: Simplified decision stub for the new single-side multi-window architecture.

The main trading logic now lives in lib/window_strategy.py.
This module is retained for backward compatibility with existing tests.
"""
import logging

log = logging.getLogger(__name__)


def make_trade_decision(
    remaining_seconds: int,
    up_price: float,
    down_price: float,
    spread: float,
    depth: float,
    scorer_result: dict,
    hard_stop_sec: int = 30,
    min_secs_main: int = 90,
    min_secs_hedge: int = 60,
    main_price_min: float = 0.50,
    main_price_max: float = 0.65,
    hedge_price_min: float = 0.05,
    hedge_price_max: float = 0.15,
    max_spread: float = 0.05,
    min_depth: float = 50,
    min_confidence: float = 0.15,
    fee: float = 0.02,
) -> dict:
    """
    Legacy decision function kept for test compatibility.
    New strategy uses lib/window_strategy.py instead.

    Returns a dict with keys: action, direction, main_price, hedge_price,
    hedge_quantity, reason.
    """
    result = {
        'action': 'SKIP',
        'direction': None,
        'main_price': 0,
        'hedge_price': None,
        'hedge_quantity': None,
        'reason': '',
    }

    if remaining_seconds < hard_stop_sec:
        result['reason'] = f"hard_stop: {remaining_seconds}s < {hard_stop_sec}s"
        return result

    if remaining_seconds < min_secs_main:
        result['reason'] = f"insufficient_time: {remaining_seconds}s < {min_secs_main}s"
        return result

    direction = scorer_result.get('direction', 'SKIP')
    if direction == 'SKIP':
        result['reason'] = f"no_signal: score={scorer_result.get('total_score', 0)}"
        return result

    confidence = abs(scorer_result.get('prob_up', 0.5) - 0.5) * 2
    if confidence < min_confidence:
        result['reason'] = f"low_confidence: {confidence:.2f} < {min_confidence}"
        return result

    if direction == 'BUY_YES':
        main_price = up_price
        bet_direction = 'UP'
    else:
        main_price = down_price
        bet_direction = 'DOWN'

    if not (main_price_min <= main_price <= main_price_max):
        result['reason'] = f"price_out_of_window: {main_price:.3f}"
        return result

    if spread > max_spread:
        result['reason'] = f"spread_too_wide: {spread:.4f} > {max_spread}"
        return result

    if depth < min_depth:
        result['reason'] = f"depth_insufficient: {depth:.1f} < {min_depth}"
        return result

    result['action'] = 'ENTER_MAIN_ONLY'
    result['direction'] = bet_direction
    result['main_price'] = main_price
    result['reason'] = f"enter: {bet_direction} @ {main_price:.3f}"
    return result
