"""
Tests for lib/market_bias.py
"""
import pytest
from lib.market_bias import Bias, compute_bias, bias_aligns_with_direction
from lib.market_data import BtcSnapshot


def make_btc_snap(price: float, price_5m_ago: float, price_15m_ago: float) -> BtcSnapshot:
    return BtcSnapshot(
        timestamp=0.0,
        price=price,
        price_5m_ago=price_5m_ago,
        price_15m_ago=price_15m_ago,
    )


class TestComputeBias:
    def test_no_data_returns_neutral(self):
        assert compute_bias(None) == Bias.NEUTRAL

    def test_no_momentum_data_returns_neutral(self):
        snap = BtcSnapshot(timestamp=0.0, price=50000.0)
        assert compute_bias(snap) == Bias.NEUTRAL

    def test_strong_up_both_timeframes(self):
        # 5m: +0.5%, 15m: +0.8% → both UP
        snap = make_btc_snap(50250, 50000, 49800)
        bias = compute_bias(snap)
        assert bias == Bias.UP

    def test_strong_down_both_timeframes(self):
        # 5m: -0.5%, 15m: -0.8%
        snap = make_btc_snap(49750, 50000, 50200)
        bias = compute_bias(snap)
        assert bias == Bias.DOWN

    def test_disagreement_returns_neutral(self):
        # 5m UP but 15m DOWN
        snap = make_btc_snap(50100, 49900, 49700)
        # 5m: +0.4%, 15m: +0.81% → both UP actually
        # Let's construct real disagreement
        snap2 = BtcSnapshot(
            timestamp=0.0,
            price=50100.0,
            price_5m_ago=49900.0,   # +0.4% → UP
            price_15m_ago=50500.0,  # -0.79% → DOWN
        )
        bias = compute_bias(snap2, require_agreement=True)
        assert bias == Bias.NEUTRAL

    def test_small_move_neutral(self):
        # 5m: +0.05%, 15m: +0.1% → below thresholds
        snap = make_btc_snap(50025, 50000, 49950)
        bias = compute_bias(snap)
        assert bias == Bias.NEUTRAL

    def test_only_5m_data_no_agreement_required(self):
        snap = BtcSnapshot(
            timestamp=0.0,
            price=50300.0,
            price_5m_ago=50000.0,   # +0.6% → UP
            price_15m_ago=None,
        )
        bias = compute_bias(snap, require_agreement=False)
        assert bias == Bias.UP

    def test_custom_thresholds(self):
        # With very high thresholds, even large moves should be neutral
        snap = make_btc_snap(50300, 50000, 49500)
        bias = compute_bias(snap, momentum_5m_threshold=0.01, momentum_15m_threshold=0.02)
        # 5m: +0.6% < 1%, 15m: +1.6% < 2% → NEUTRAL
        assert bias == Bias.NEUTRAL


class TestBiasAligns:
    def test_up_aligns_with_up(self):
        assert bias_aligns_with_direction(Bias.UP, "UP") is True

    def test_up_does_not_align_with_down(self):
        assert bias_aligns_with_direction(Bias.UP, "DOWN") is False

    def test_down_aligns_with_down(self):
        assert bias_aligns_with_direction(Bias.DOWN, "DOWN") is True

    def test_neutral_aligns_with_anything(self):
        assert bias_aligns_with_direction(Bias.NEUTRAL, "UP") is True
        assert bias_aligns_with_direction(Bias.NEUTRAL, "DOWN") is True

    def test_case_insensitive_direction(self):
        assert bias_aligns_with_direction(Bias.UP, "up") is True
        assert bias_aligns_with_direction(Bias.DOWN, "down") is True
