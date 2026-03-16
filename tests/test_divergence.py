"""Unit tests for price divergence calculation."""
from __future__ import annotations

import pytest

from strategy.divergence import (
    absolute_divergence,
    get_ask_prices,
    is_diverged,
    relative_divergence,
)
from polymarket.models import OrderBook


class TestAbsoluteDivergence:
    def test_basic(self):
        assert round(absolute_divergence(0.65, 0.40), 4) == 0.25

    def test_reversed_order(self):
        """Order of arguments should not matter."""
        assert absolute_divergence(0.40, 0.65) == absolute_divergence(0.65, 0.40)

    def test_equal_prices(self):
        assert absolute_divergence(0.50, 0.50) == 0.0

    def test_max_divergence(self):
        assert absolute_divergence(1.0, 0.0) == 1.0


class TestRelativeDivergence:
    def test_basic(self):
        result = relative_divergence(0.65, 0.40)
        assert round(result, 4) == 0.625

    def test_zero_denom(self):
        assert relative_divergence(0.10, 0.0) == 0.0

    def test_equal_prices(self):
        assert relative_divergence(0.50, 0.50) == 0.0


class TestIsDiverged:
    def test_default_threshold_diverged(self):
        assert is_diverged(0.65, 0.40) is True

    def test_default_threshold_close(self):
        assert is_diverged(0.55, 0.50) is False

    def test_at_exactly_threshold(self):
        assert is_diverged(0.60, 0.50, threshold=0.10) is True

    def test_just_below_threshold(self):
        assert is_diverged(0.59, 0.50, threshold=0.10) is False

    def test_relative_mode(self):
        # abs diff = 0.10, relative = 0.10/0.40 = 0.25
        assert is_diverged(0.50, 0.40, threshold=0.20, use_relative=True) is True

    def test_relative_mode_below(self):
        # abs diff = 0.05, relative = 0.05/0.50 = 0.10
        assert is_diverged(0.55, 0.50, threshold=0.20, use_relative=True) is False


class TestGetAskPrices:
    def _make_book(self, ask_price):
        book = OrderBook(token_id="t1")
        if ask_price is not None:
            book.asks = [(ask_price, 100.0)]
        return book

    def test_both_present(self):
        up = self._make_book(0.65)
        down = self._make_book(0.40)
        up_ask, down_ask = get_ask_prices(up, down)
        assert up_ask == 0.65
        assert down_ask == 0.40

    def test_one_empty(self):
        up = self._make_book(None)
        down = self._make_book(0.40)
        up_ask, down_ask = get_ask_prices(up, down)
        assert up_ask is None
        assert down_ask == 0.40
