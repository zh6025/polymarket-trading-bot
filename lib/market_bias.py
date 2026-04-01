"""
MarketBias: Compute background market bias (UP / DOWN / NEUTRAL)
from BTC trend and momentum inputs.
"""
import logging
from enum import Enum
from typing import Optional
from lib.market_data import BtcSnapshot

log = logging.getLogger(__name__)


class Bias(str, Enum):
    UP = "UP"
    DOWN = "DOWN"
    NEUTRAL = "NEUTRAL"


def compute_bias(
    btc: Optional[BtcSnapshot],
    momentum_5m_threshold: float = 0.0015,   # 0.15% move = directional
    momentum_15m_threshold: float = 0.003,    # 0.30% move = strong trend
    require_agreement: bool = True,
) -> Bias:
    """
    Compute market bias from BTC snapshot.

    Args:
        btc: BTC price snapshot
        momentum_5m_threshold: Minimum 5m move to count as directional
        momentum_15m_threshold: Minimum 15m move to count as trend
        require_agreement: If True, both timeframes must agree for non-NEUTRAL bias

    Returns:
        Bias.UP, Bias.DOWN, or Bias.NEUTRAL
    """
    if btc is None:
        log.warning("No BTC data available, defaulting to NEUTRAL bias")
        return Bias.NEUTRAL

    m5 = btc.momentum_5m
    m15 = btc.momentum_15m

    if m5 is None and m15 is None:
        return Bias.NEUTRAL

    def direction_from_momentum(m: Optional[float], threshold: float) -> Optional[str]:
        if m is None:
            return None
        if m > threshold:
            return "UP"
        if m < -threshold:
            return "DOWN"
        return "NEUTRAL"

    dir5 = direction_from_momentum(m5, momentum_5m_threshold)
    dir15 = direction_from_momentum(m15, momentum_15m_threshold)

    if require_agreement and dir5 is not None and dir15 is not None:
        if dir5 == dir15 and dir5 != "NEUTRAL":
            bias = Bias(dir5)
            log.debug(f"Bias={bias} (5m={m5:.4f}, 15m={m15:.4f})")
            return bias
        return Bias.NEUTRAL

    for d in [dir5, dir15]:
        if d is not None and d != "NEUTRAL":
            return Bias(d)

    return Bias.NEUTRAL


def bias_aligns_with_direction(bias: Bias, direction: str) -> bool:
    """Check if market bias aligns with intended trade direction"""
    if bias == Bias.NEUTRAL:
        return True  # neutral doesn't block
    return bias.value == direction.upper()
