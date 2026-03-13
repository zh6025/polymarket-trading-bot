"""Abstract base class for BTC price feeds."""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections import deque
from typing import Optional


class PriceFeed(ABC):
    """Abstract BTC/USD price feed.

    Provides:
      - ``latest_price``: most recent price
      - ``history``: a deque of (timestamp, price) tuples
    """

    # How many data points to keep in the rolling history
    MAX_HISTORY = 200

    def __init__(self) -> None:
        self._history: deque[tuple[float, float]] = deque(maxlen=self.MAX_HISTORY)

    @abstractmethod
    def start(self) -> None:
        """Start data collection (connect websocket, begin polling, etc.)."""

    @abstractmethod
    def stop(self) -> None:
        """Stop data collection."""

    @property
    def latest_price(self) -> Optional[float]:
        """Return the most recent price or None if no data yet."""
        if self._history:
            return self._history[-1][1]
        return None

    @property
    def history(self) -> list[tuple[float, float]]:
        """Return a snapshot list of (timestamp, price) tuples, oldest first."""
        return list(self._history)

    def price_n_seconds_ago(self, seconds: float) -> Optional[float]:
        """Return the closest recorded price from ``seconds`` seconds ago."""
        target = time.time() - seconds
        best = None
        best_diff = float("inf")
        for ts, price in self._history:
            diff = abs(ts - target)
            if diff < best_diff:
                best_diff = diff
                best = price
        return best

    def _record(self, price: float, ts: Optional[float] = None) -> None:
        """Record a new price observation."""
        self._history.append((ts or time.time(), price))
