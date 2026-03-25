"""Tests for lib/direction_scorer.py"""
import pytest
from lib.direction_scorer import DirectionScorer


@pytest.fixture
def scorer():
    return DirectionScorer()


class TestIndividualScorers:
    def test_ema_golden_cross(self, scorer):
        score = scorer.score_ema_cross(ema_fast=101, ema_slow=100, prev_ema_fast=99, prev_ema_slow=100)
        assert score == 80.0

    def test_ema_death_cross(self, scorer):
        score = scorer.score_ema_cross(ema_fast=99, ema_slow=100, prev_ema_fast=101, prev_ema_slow=100)
        assert score == -80.0

    def test_ema_bullish_continuation(self, scorer):
        score = scorer.score_ema_cross(ema_fast=102, ema_slow=100, prev_ema_fast=101, prev_ema_slow=100)
        assert 0 < score <= 60

    def test_rsi_overbought_rising(self, scorer):
        score = scorer.score_rsi(75, 72)
        assert score == 50.0

    def test_rsi_oversold_falling(self, scorer):
        # Contrarian: oversold AND still falling → expect bounce → positive score
        score = scorer.score_rsi(25, 28)
        assert score == 50.0

    def test_rsi_oversold_rising(self, scorer):
        # Contrarian: oversold AND rising → bounce already started → negative (overbought reversal)
        score = scorer.score_rsi(28, 25)
        assert score == -50.0

    def test_vwap_above(self, scorer):
        score = scorer.score_vwap(current_price=100.2, vwap=100.0)
        assert score > 0

    def test_vwap_below(self, scorer):
        score = scorer.score_vwap(current_price=99.8, vwap=100.0)
        assert score < 0

    def test_volume_surge_up(self, scorer):
        score = scorer.score_volume_surge(current_vol=300, avg_vol=100, price_change=50)
        assert score > 0

    def test_volume_surge_down(self, scorer):
        score = scorer.score_volume_surge(current_vol=300, avg_vol=100, price_change=-50)
        assert score < 0

    def test_cvd_positive(self, scorer):
        assert scorer.score_cvd(5.0) > 0

    def test_cvd_negative(self, scorer):
        assert scorer.score_cvd(-5.0) < 0

    def test_orderbook_bid_heavy(self, scorer):
        assert scorer.score_orderbook(bid_depth=200, ask_depth=100) > 0

    def test_orderbook_ask_heavy(self, scorer):
        assert scorer.score_orderbook(bid_depth=50, ask_depth=200) < 0

    def test_funding_rate_moderate_positive(self, scorer):
        assert scorer.score_funding_rate(0.01) == 30.0

    def test_funding_rate_extreme_positive(self, scorer):
        assert scorer.score_funding_rate(0.06) == -20.0

    def test_oi_new_longs(self, scorer):
        assert scorer.score_oi_change(oi_change_pct=3, price_change=100) == 50.0

    def test_oi_new_shorts(self, scorer):
        assert scorer.score_oi_change(oi_change_pct=3, price_change=-100) == -50.0


class TestComputeFinalScore:
    def test_strong_bull_signals_give_buy_yes(self, scorer):
        signals = {
            "ema_cross": 80, "rsi_trend": 50, "vwap_position": 50,
            "volume_surge": 70, "cvd_direction": 90, "orderbook_ratio": 60,
            "funding_rate": 30, "oi_change": 50, "macro_sentiment": 20,
        }
        result = scorer.compute_final_score(signals)
        assert result["action"] == "BUY_YES"
        assert result["confidence"] == "HIGH"
        assert result["prob_up"] > 0.5

    def test_strong_bear_signals_give_buy_no(self, scorer):
        signals = {
            "ema_cross": -80, "rsi_trend": -50, "vwap_position": -50,
            "volume_surge": -70, "cvd_direction": -90, "orderbook_ratio": -60,
            "funding_rate": -30, "oi_change": -50, "macro_sentiment": -20,
        }
        result = scorer.compute_final_score(signals)
        assert result["action"] == "BUY_NO"
        assert result["confidence"] == "HIGH"
        assert result["prob_down"] > 0.5

    def test_flat_signals_give_skip(self, scorer):
        result = scorer.compute_final_score({})
        assert result["action"] == "SKIP"
        assert result["confidence"] == "LOW"
        assert abs(result["prob_up"] - 0.5) < 0.01

    def test_output_keys_present(self, scorer):
        result = scorer.compute_final_score({"ema_cross": 30})
        for key in ("total_score", "prob_up", "prob_down", "action", "confidence", "details"):
            assert key in result

    def test_prob_sums_to_one(self, scorer):
        result = scorer.compute_final_score({"cvd_direction": 50})
        assert abs(result["prob_up"] + result["prob_down"] - 1.0) < 1e-6
