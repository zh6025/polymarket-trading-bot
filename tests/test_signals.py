"""Unit tests for trend signals."""
from __future__ import annotations

import time
from collections import deque

import pytest

from strategy.signals import Trend, is_trend_reversal, trend_from_returns


class TestTrendFromReturns:
    def test_both_up(self):
        assert trend_from_returns(0.005, 0.003) == Trend.UP

    def test_both_down(self):
        assert trend_from_returns(-0.005, -0.003) == Trend.DOWN

    def test_mixed_returns(self):
        # One up, one down → NEUTRAL
        assert trend_from_returns(0.005, -0.005) == Trend.NEUTRAL

    def test_both_small(self):
        assert trend_from_returns(0.0001, 0.0001) == Trend.NEUTRAL

    def test_one_none(self):
        # Only 5m available, it's up
        assert trend_from_returns(0.005, None) == Trend.UP

    def test_both_none(self):
        assert trend_from_returns(None, None) == Trend.NEUTRAL

    def test_custom_threshold(self):
        # Return of 0.002 is above default 0.001 but below 0.005 threshold
        assert trend_from_returns(0.002, 0.002, threshold_pct=0.005) == Trend.NEUTRAL
        assert trend_from_returns(0.006, 0.006, threshold_pct=0.005) == Trend.UP


class TestIsTrendReversal:
    def test_up_to_down_is_reversal(self):
        assert is_trend_reversal(Trend.UP, Trend.DOWN) is True

    def test_down_to_up_is_reversal(self):
        assert is_trend_reversal(Trend.DOWN, Trend.UP) is True

    def test_same_direction_no_reversal(self):
        assert is_trend_reversal(Trend.UP, Trend.UP) is False

    def test_neutral_initial_no_reversal(self):
        assert is_trend_reversal(Trend.NEUTRAL, Trend.DOWN) is False

    def test_neutral_current_no_reversal(self):
        assert is_trend_reversal(Trend.UP, Trend.NEUTRAL) is False

    def test_both_neutral(self):
        assert is_trend_reversal(Trend.NEUTRAL, Trend.NEUTRAL) is False
