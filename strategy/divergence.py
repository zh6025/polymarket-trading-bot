"""Price divergence calculation for UP/DOWN outcomes.

Provides a configurable measure of how far apart the two sides' ask prices
are.  The strategy enters when the divergence is at or above a threshold.
"""
from __future__ import annotations

from typing import Optional

from polymarket.models import OrderBook


def absolute_divergence(up_ask: float, down_ask: float) -> float:
    """Return the absolute difference between the two ask prices.

    Both prices should be in the $0..$1 range (Polymarket outcome prices).

    >>> round(absolute_divergence(0.65, 0.40), 4)
    0.25
    """
    return round(abs(up_ask - down_ask), 10)


def relative_divergence(up_ask: float, down_ask: float) -> float:
    """Return the relative divergence normalised by the smaller ask price.

    For example, asks of 0.65 and 0.40 give a relative divergence of 0.625.

    >>> round(relative_divergence(0.65, 0.40), 4)
    0.625
    """
    denom = min(up_ask, down_ask)
    if denom <= 0:
        return 0.0
    return abs(up_ask - down_ask) / denom


def is_diverged(
    up_ask: float,
    down_ask: float,
    threshold: float = 0.10,
    use_relative: bool = False,
) -> bool:
    """Return True when the price divergence meets or exceeds *threshold*.

    Args:
        up_ask: Best ask price for the UP outcome.
        down_ask: Best ask price for the DOWN outcome.
        threshold: Minimum divergence required.  Defaults to 0.10 (absolute).
        use_relative: If True, use relative divergence instead of absolute.

    Returns:
        True if an entry signal is present.

    >>> is_diverged(0.65, 0.40)
    True
    >>> is_diverged(0.55, 0.50)
    False
    >>> is_diverged(0.55, 0.50, threshold=0.04)
    True
    """
    if use_relative:
        return relative_divergence(up_ask, down_ask) >= threshold
    return absolute_divergence(up_ask, down_ask) >= threshold


def get_ask_prices(
    book_up: OrderBook,
    book_down: OrderBook,
) -> tuple[Optional[float], Optional[float]]:
    """Extract the best ask prices from two order books.

    Returns a tuple (up_ask, down_ask), either of which may be None if the
    corresponding order book has no asks.
    """
    return book_up.best_ask, book_down.best_ask
