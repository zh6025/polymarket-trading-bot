"""
Tests for lib/direction_scorer.py
"""
import math
import pytest
from unittest.mock import patch, MagicMock
from lib.direction_scorer import DirectionScorer


def make_kline(open_=100, high=105, low=95, close=102, volume=10):
    """Helper to create a mock kline entry."""
    return [0, str(open_), str(high), str(low), str(close), str(volume),
            0, '0', 0, '0', '0', '0']


def make_klines(n=30, trend='up'):
    """Generate a list of mock klines with a trend."""
    klines = []
    price = 100.0
    for i in range(n):
        if trend == 'up':
            price += 0.5
        elif trend == 'down':
            price -= 0.5
        klines.append(make_kline(
            open_=price - 0.3,
            high=price + 1,
            low=price - 1,
            close=price,
            volume=10 + i * 0.1,
        ))
    return klines


class TestDirectionScorerSignals:
    def setup_method(self):
        self.scorer = DirectionScorer()

    def test_score_ema_cross_bullish(self):
        """Uptrend klines should produce positive EMA cross score."""
        klines = make_klines(n=30, trend='up')
        score = self.scorer.score_ema_cross(klines)
        assert score >= 0

    def test_score_ema_cross_bearish(self):
        """Downtrend klines should produce negative EMA cross score."""
        klines = make_klines(n=30, trend='down')
        score = self.scorer.score_ema_cross(klines)
        assert score <= 0

    def test_score_ema_cross_insufficient_data(self):
        """Fewer than 14 klines should return 0."""
        klines = make_klines(n=10, trend='up')
        score = self.scorer.score_ema_cross(klines)
        assert score == 0

    def test_score_rsi_insufficient_data(self):
        klines = make_klines(n=10)
        score = self.scorer.score_rsi(klines)
        assert score == 0

    def test_score_vwap_empty(self):
        score = self.scorer.score_vwap([])
        assert score == 0

    def test_score_cvd_empty(self):
        score = self.scorer.score_cvd([])
        assert score == 0

    def test_score_orderbook_both_zero(self):
        score = self.scorer.score_orderbook(0, 0)
        assert score == 0

    def test_score_orderbook_no_depth_zero(self):
        score = self.scorer.score_orderbook(yes_depth=100, no_depth=0)
        assert score == 50

    def test_score_orderbook_yes_heavy(self):
        score = self.scorer.score_orderbook(yes_depth=200, no_depth=100)
        assert score > 0

    def test_score_orderbook_no_heavy(self):
        score = self.scorer.score_orderbook(yes_depth=50, no_depth=200)
        assert score < 0

    def test_score_volume_surge_insufficient_data(self):
        klines = make_klines(n=10)
        score = self.scorer.score_volume_surge(klines)
        assert score == 0

    def test_score_macro_momentum_up(self):
        klines = make_klines(n=20, trend='up')
        score = self.scorer.score_macro_momentum(klines)
        assert score >= 0

    def test_score_oi_change_insufficient(self):
        klines = make_klines(n=5)
        score = self.scorer.score_oi_change(klines)
        assert score == 0


class TestDirectionScorerFinalScore:
    def setup_method(self):
        self.scorer = DirectionScorer()

    @patch.object(DirectionScorer, '_get_klines')
    @patch.object(DirectionScorer, '_get_funding_rate', return_value=0.0)
    def test_prob_up_in_range(self, mock_funding, mock_klines):
        """prob_up must always be in [0, 1]."""
        mock_klines.return_value = make_klines(n=30, trend='up')
        result = self.scorer.compute_final_score()
        assert 0 <= result['prob_up'] <= 1

    @patch.object(DirectionScorer, '_get_klines')
    @patch.object(DirectionScorer, '_get_funding_rate', return_value=0.0)
    def test_prob_down_complements_up(self, mock_funding, mock_klines):
        mock_klines.return_value = make_klines(n=30, trend='up')
        result = self.scorer.compute_final_score()
        assert abs(result['prob_up'] + result['prob_down'] - 1.0) < 1e-6

    @patch.object(DirectionScorer, '_get_klines')
    @patch.object(DirectionScorer, '_get_funding_rate', return_value=0.0)
    def test_direction_is_valid_string(self, mock_funding, mock_klines):
        mock_klines.return_value = make_klines(n=30, trend='up')
        result = self.scorer.compute_final_score()
        assert result['direction'] in ('BUY_YES', 'BUY_NO', 'SKIP')

    @patch.object(DirectionScorer, '_get_klines')
    @patch.object(DirectionScorer, '_get_funding_rate', return_value=0.0)
    def test_signals_dict_has_all_keys(self, mock_funding, mock_klines):
        mock_klines.return_value = make_klines(n=30, trend='up')
        result = self.scorer.compute_final_score()
        expected_keys = set(DirectionScorer.WEIGHTS.keys())
        assert set(result['signals'].keys()) == expected_keys

    @patch.object(DirectionScorer, '_get_klines')
    @patch.object(DirectionScorer, '_get_funding_rate', return_value=0.0)
    def test_empty_klines_returns_skip(self, mock_funding, mock_klines):
        """With no data, all signals return 0 and direction should be SKIP."""
        mock_klines.return_value = []
        result = self.scorer.compute_final_score()
        assert result['direction'] == 'SKIP'

    def test_kline_cache_ttl(self):
        """Cache should return same data within TTL."""
        scorer = DirectionScorer(cache_ttl=60)
        with patch('lib.direction_scorer.requests.get') as mock_get:
            mock_resp = MagicMock()
            mock_resp.json.return_value = make_klines(n=5)
            mock_resp.raise_for_status.return_value = None
            mock_get.return_value = mock_resp

            # First call hits API
            scorer._get_klines(limit=5)
            assert mock_get.call_count == 1

            # Second call within TTL uses cache
            scorer._get_klines(limit=5)
            assert mock_get.call_count == 1
