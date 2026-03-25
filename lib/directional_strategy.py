"""
Directional strategy: EMA-3/EMA-8 crossover + ATR(10) filter for BTC 5-min markets.
"""
import logging
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)


def _ema(prices: List[float], period: int) -> List[float]:
    """Compute EMA for a list of prices."""
    if len(prices) < period:
        return []
    k = 2.0 / (period + 1)
    result = [sum(prices[:period]) / period]
    for p in prices[period:]:
        result.append(p * k + result[-1] * (1 - k))
    return result


def _atr(klines: List[List], period: int = 10) -> Optional[float]:
    """
    Compute ATR from klines [[open_time,open,high,low,close,...]].
    Returns None if insufficient data.
    """
    if len(klines) < period + 1:
        return None
    trs = []
    for i in range(1, len(klines)):
        high = float(klines[i][2])
        low = float(klines[i][3])
        prev_close = float(klines[i - 1][4])
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    recent_trs = trs[-period:]
    return sum(recent_trs) / len(recent_trs)


class DirectionalStrategy:
    """
    EMA-3/EMA-8 crossover strategy with ATR(10) volatility filter.

    generate_signal() → 'UP' | 'DOWN' | 'SKIP'
    decide_bet(signal, up_ask, down_ask) → order dict or None
    """

    def __init__(
        self,
        fast_period: int = 3,
        slow_period: int = 8,
        atr_period: int = 10,
        atr_threshold_pct: float = 0.0003,
        max_entry_price: float = 0.55,
        bet_size: float = 5.0,
        signal_buffer: float = 0.0002,
    ):
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.atr_period = atr_period
        self.atr_threshold_pct = atr_threshold_pct
        self.max_entry_price = max_entry_price
        self.bet_size = bet_size
        self.signal_buffer = signal_buffer

    def generate_signal(self, klines: List[List]) -> str:
        """
        Compute EMA crossover signal.

        Returns 'UP', 'DOWN', or 'SKIP'.
        """
        closes = [float(k[4]) for k in klines]
        min_len = self.slow_period + 2
        if len(closes) < min_len:
            logger.debug("generate_signal: insufficient kline data")
            return "SKIP"

        ema_fast = _ema(closes, self.fast_period)
        ema_slow = _ema(closes, self.slow_period)

        if len(ema_fast) < 2 or len(ema_slow) < 2:
            return "SKIP"

        # ATR filter
        atr = _atr(klines, self.atr_period)
        if atr is None:
            return "SKIP"
        current_price = closes[-1]
        if current_price <= 0:
            return "SKIP"
        atr_pct = atr / current_price
        if atr_pct < self.atr_threshold_pct:
            logger.debug(f"ATR too low: {atr_pct:.5f} < {self.atr_threshold_pct}")
            return "SKIP"

        fast_now, fast_prev = ema_fast[-1], ema_fast[-2]
        slow_now, slow_prev = ema_slow[-1], ema_slow[-2]

        # Golden cross: fast crosses above slow
        if fast_now > slow_now + self.signal_buffer and fast_prev <= slow_prev:
            return "UP"
        # Death cross: fast crosses below slow
        if fast_now < slow_now - self.signal_buffer and fast_prev >= slow_prev:
            return "DOWN"

        return "SKIP"

    def decide_bet(
        self,
        signal: str,
        up_ask: float,
        down_ask: float,
        up_token_id: str = "",
        down_token_id: str = "",
    ) -> Optional[Dict[str, Any]]:
        """
        Given a signal, return an order dict or None if price guard fails.

        Order dict keys: outcome, token_id, side, price, size
        """
        if signal == "UP":
            if up_ask > self.max_entry_price:
                logger.info(f"UP ask {up_ask:.4f} > max entry {self.max_entry_price}")
                return None
            return {
                "outcome": "UP",
                "token_id": up_token_id,
                "side": "BUY",
                "price": up_ask,
                "size": self.bet_size,
            }
        if signal == "DOWN":
            if down_ask > self.max_entry_price:
                logger.info(f"DOWN ask {down_ask:.4f} > max entry {self.max_entry_price}")
                return None
            return {
                "outcome": "DOWN",
                "token_id": down_token_id,
                "side": "BUY",
                "price": down_ask,
                "size": self.bet_size,
            }
        return None
