"""BTC trend signals for direction selection.

Computes short-term (5-minute) and medium-term (15-minute) trend signals
from a price feed.  The combined signal is used to decide whether to buy
the UP or DOWN outcome.
"""
from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Optional

from feeds.base import PriceFeed

logger = logging.getLogger(__name__)


class Trend(str, Enum):
    UP = "UP"
    DOWN = "DOWN"
    NEUTRAL = "NEUTRAL"


def price_return(feed: PriceFeed, seconds_back: float) -> Optional[float]:
    """Compute the price return over the last *seconds_back* seconds.

    Returns (current_price / past_price - 1) or None if no historical data.
    """
    current = feed.latest_price
    past = feed.price_n_seconds_ago(seconds_back)
    if current is None or past is None or past == 0:
        return None
    return (current / past) - 1


def trend_from_returns(
    ret_5m: Optional[float],
    ret_15m: Optional[float],
    threshold_pct: float = 0.001,
) -> Trend:
    """Derive a directional bias from 5m and 15m returns.

    Logic:
    - Both returns above threshold  → UP
    - Both returns below -threshold → DOWN
    - Mixed or small returns        → NEUTRAL

    Args:
        ret_5m: 5-minute price return (e.g. 0.005 = +0.5%).
        ret_15m: 15-minute price return.
        threshold_pct: Minimum absolute return to be considered directional.
            Default 0.001 (0.1%).
    """
    if ret_5m is None and ret_15m is None:
        return Trend.NEUTRAL

    up_votes = 0
    down_votes = 0

    for ret in (ret_5m, ret_15m):
        if ret is None:
            continue
        if ret >= threshold_pct:
            up_votes += 1
        elif ret <= -threshold_pct:
            down_votes += 1

    if up_votes > down_votes:
        return Trend.UP
    if down_votes > up_votes:
        return Trend.DOWN
    return Trend.NEUTRAL


def get_trend(
    feed: PriceFeed,
    threshold_pct: float = 0.001,
) -> Trend:
    """Compute the current UP/DOWN/NEUTRAL bias from the live price feed.

    Uses 5-minute and 15-minute returns.
    """
    ret_5m = price_return(feed, 300)   # 5 minutes
    ret_15m = price_return(feed, 900)  # 15 minutes
    trend = trend_from_returns(ret_5m, ret_15m, threshold_pct)
    logger.debug(
        "Trend signals",
        extra={
            "ret_5m": ret_5m,
            "ret_15m": ret_15m,
            "trend": trend.value,
        },
    )
    return trend


def is_trend_reversal(
    initial_trend: Trend,
    current_trend: Trend,
) -> bool:
    """Return True when the current trend is the opposite of *initial_trend*.

    NEUTRAL does not count as a reversal to avoid premature exits on
    sideways markets.
    """
    if initial_trend == Trend.NEUTRAL or current_trend == Trend.NEUTRAL:
        return False
    return initial_trend != current_trend
