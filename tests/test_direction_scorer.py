"""
tests/test_direction_scorer.py

Unit tests for lib/direction_scorer.DirectionScorer.
All external HTTP calls are mocked so these tests run offline.
"""
import math
import unittest
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# We must stub out 'requests' before the module is imported so that no real
# network calls occur during test collection.
# ---------------------------------------------------------------------------
import sys

# Pre-import the module so we can patch its internals
import importlib


def _make_kline(open_=100.0, high=105.0, low=95.0, close=102.0, volume=1000.0):
    """Return a minimal Binance-style kline list."""
    return [
        0,        # open time
        str(open_),
        str(high),
        str(low),
        str(close),
        str(volume),
        0, 0, 0, 0, 0, 0,
    ]


def _make_klines(n=30, base_close=100.0, step=0.5):
    """Generate a synthetic kline sequence with a gentle uptrend."""
    klines = []
    price = base_close
    for i in range(n):
        open_ = price
        close = price + step
        high = close + 1.0
        low = open_ - 1.0
        klines.append(_make_kline(open_, high, low, close, volume=1000.0 + i * 10))
        price = close
    return klines


class TestDirectionScorerSignals(unittest.TestCase):
    """Test each of the 9 signal methods in isolation."""

    def setUp(self):
        from lib.direction_scorer import DirectionScorer
        self.scorer = DirectionScorer()
        self.klines_up = _make_klines(n=30, base_close=100.0, step=0.5)
        self.klines_down = _make_klines(n=30, base_close=100.0, step=-0.5)
        self.klines_flat = _make_klines(n=30, base_close=100.0, step=0.0)

    # ---- score_ema_cross -------------------------------------------------

    def test_ema_cross_uptrend_positive(self):
        score = self.scorer.score_ema_cross(self.klines_up)
        self.assertGreater(score, 0, "Uptrend should produce positive EMA cross score")

    def test_ema_cross_downtrend_negative(self):
        score = self.scorer.score_ema_cross(self.klines_down)
        self.assertLess(score, 0, "Downtrend should produce negative EMA cross score")

    def test_ema_cross_bounds(self):
        for klines in (self.klines_up, self.klines_down, self.klines_flat):
            score = self.scorer.score_ema_cross(klines)
            self.assertGreaterEqual(score, -1.0)
            self.assertLessEqual(score, 1.0)

    def test_ema_cross_insufficient_data(self):
        score = self.scorer.score_ema_cross(_make_klines(n=5))
        self.assertEqual(score, 0.0)

    # ---- score_rsi -------------------------------------------------------

    def test_rsi_uptrend_positive(self):
        score = self.scorer.score_rsi(self.klines_up)
        self.assertGreater(score, 0)

    def test_rsi_downtrend_negative(self):
        score = self.scorer.score_rsi(self.klines_down)
        self.assertLess(score, 0)

    def test_rsi_bounds(self):
        for klines in (self.klines_up, self.klines_down):
            score = self.scorer.score_rsi(klines)
            self.assertGreaterEqual(score, -1.0)
            self.assertLessEqual(score, 1.0)

    def test_rsi_insufficient_data(self):
        score = self.scorer.score_rsi(_make_klines(n=5))
        self.assertEqual(score, 0.0)

    # ---- score_vwap ------------------------------------------------------

    def test_vwap_price_above(self):
        klines = _make_klines(n=20, base_close=100.0, step=0.0)
        score = self.scorer.score_vwap(klines, current_price=105.0)
        self.assertGreater(score, 0)

    def test_vwap_price_below(self):
        klines = _make_klines(n=20, base_close=100.0, step=0.0)
        score = self.scorer.score_vwap(klines, current_price=95.0)
        self.assertLess(score, 0)

    def test_vwap_no_price(self):
        score = self.scorer.score_vwap(self.klines_up, current_price=None)
        self.assertEqual(score, 0.0)

    def test_vwap_bounds(self):
        klines = _make_klines(n=20, base_close=100.0, step=0.0)
        for price in [80.0, 90.0, 100.0, 110.0, 120.0]:
            score = self.scorer.score_vwap(klines, current_price=price)
            self.assertGreaterEqual(score, -1.0)
            self.assertLessEqual(score, 1.0)

    # ---- score_volume_surge ----------------------------------------------

    def test_volume_surge_bullish(self):
        klines = _make_klines(n=25, base_close=100.0, step=0.1)
        # Amplify last 3 candles' volume to trigger surge
        for i in range(-3, 0):
            klines[i][5] = str(10_000.0)
        score = self.scorer.score_volume_surge(klines)
        self.assertGreater(score, 0)

    def test_volume_surge_bearish(self):
        klines = _make_klines(n=25, base_close=100.0, step=-0.1)
        for i in range(-3, 0):
            klines[i][5] = str(10_000.0)
        score = self.scorer.score_volume_surge(klines)
        self.assertLess(score, 0)

    def test_volume_surge_no_surge(self):
        klines = _make_klines(n=25, base_close=100.0, step=0.1)
        # Keep volumes uniform — no surge
        for k in klines:
            k[5] = str(1000.0)
        score = self.scorer.score_volume_surge(klines)
        self.assertEqual(score, 0.0)

    # ---- score_cvd -------------------------------------------------------

    def test_cvd_bullish_candles_positive(self):
        # All candles close > open → buyers dominant
        klines = _make_klines(n=15, base_close=100.0, step=1.0)
        score = self.scorer.score_cvd(klines)
        self.assertGreater(score, 0)

    def test_cvd_bearish_candles_negative(self):
        klines = _make_klines(n=15, base_close=100.0, step=-1.0)
        score = self.scorer.score_cvd(klines)
        self.assertLess(score, 0)

    def test_cvd_bounds(self):
        for klines in (self.klines_up, self.klines_down):
            score = self.scorer.score_cvd(klines)
            self.assertGreaterEqual(score, -1.0)
            self.assertLessEqual(score, 1.0)

    # ---- score_orderbook ------------------------------------------------

    def test_orderbook_no_client_returns_zero(self):
        self.scorer.polymarket_client = None
        score = self.scorer.score_orderbook()
        self.assertEqual(score, 0.0)

    def test_orderbook_yes_dominant_positive(self):
        mock_client = MagicMock()
        mock_client.get_orderbook.side_effect = [
            # YES orderbook — large depth
            {"bids": [{"price": "0.60", "size": "1000"}], "asks": []},
            # NO orderbook — small depth
            {"bids": [{"price": "0.10", "size": "10"}], "asks": []},
        ]
        self.scorer.polymarket_client = mock_client
        self.scorer.yes_token_id = "yes_token"
        self.scorer.no_token_id  = "no_token"
        score = self.scorer.score_orderbook()
        self.assertGreater(score, 0)

    def test_orderbook_no_dominant_negative(self):
        mock_client = MagicMock()
        mock_client.get_orderbook.side_effect = [
            # YES orderbook — small depth
            {"bids": [{"price": "0.60", "size": "10"}], "asks": []},
            # NO orderbook — large depth
            {"bids": [{"price": "0.10", "size": "1000"}], "asks": []},
        ]
        self.scorer.polymarket_client = mock_client
        self.scorer.yes_token_id = "yes_token"
        self.scorer.no_token_id  = "no_token"
        score = self.scorer.score_orderbook()
        self.assertLess(score, 0)

    # ---- score_funding_rate ---------------------------------------------

    @patch("lib.direction_scorer.requests.get")
    def test_funding_rate_positive_bearish(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: [{"fundingRate": "0.001"}],
        )
        mock_get.return_value.raise_for_status = lambda: None
        score = self.scorer.score_funding_rate()
        self.assertLess(score, 0, "Positive funding rate → bearish → negative score")

    @patch("lib.direction_scorer.requests.get")
    def test_funding_rate_negative_bullish(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: [{"fundingRate": "-0.001"}],
        )
        mock_get.return_value.raise_for_status = lambda: None
        score = self.scorer.score_funding_rate()
        self.assertGreater(score, 0, "Negative funding rate → bullish → positive score")

    @patch("lib.direction_scorer.requests.get")
    def test_funding_rate_error_returns_zero(self, mock_get):
        mock_get.side_effect = Exception("network error")
        score = self.scorer.score_funding_rate()
        self.assertEqual(score, 0.0)

    # ---- score_oi_change ------------------------------------------------

    @patch("lib.direction_scorer.requests.get")
    def test_oi_change_error_returns_zero(self, mock_get):
        mock_get.side_effect = Exception("network error")
        score = self.scorer.score_oi_change(50000.0)
        self.assertEqual(score, 0.0)

    # ---- score_macro_momentum -------------------------------------------

    def test_macro_momentum_both_positive(self):
        klines5  = _make_klines(n=5, base_close=100.0, step=1.0)
        klines15 = _make_klines(n=5, base_close=100.0, step=1.0)
        score = self.scorer.score_macro_momentum(klines5, klines15)
        self.assertEqual(score, 1.0)

    def test_macro_momentum_both_negative(self):
        klines5  = _make_klines(n=5, base_close=100.0, step=-1.0)
        klines15 = _make_klines(n=5, base_close=100.0, step=-1.0)
        score = self.scorer.score_macro_momentum(klines5, klines15)
        self.assertEqual(score, -1.0)

    def test_macro_momentum_mixed(self):
        klines5  = _make_klines(n=5, base_close=100.0, step=1.0)
        klines15 = _make_klines(n=5, base_close=100.0, step=-1.0)
        score = self.scorer.score_macro_momentum(klines5, klines15)
        self.assertNotEqual(abs(score), 1.0)

    def test_macro_momentum_bounds(self):
        klines5  = _make_klines(n=5)
        klines15 = _make_klines(n=5)
        score = self.scorer.score_macro_momentum(klines5, klines15)
        self.assertGreaterEqual(score, -1.0)
        self.assertLessEqual(score, 1.0)

    # ---- compute_final_score (integration, all HTTP mocked) --------------

    @patch("lib.direction_scorer.requests.get")
    def test_compute_final_score_structure(self, mock_get):
        """compute_final_score returns expected keys and value ranges."""
        klines = _make_klines(n=30, base_close=50000.0, step=10.0)

        def fake_get(url, params=None, timeout=None):
            resp = MagicMock()
            resp.raise_for_status = lambda: None
            if "klines" in url:
                resp.json = lambda: klines
            elif "ticker/price" in url:
                resp.json = lambda: {"price": "50300.0"}
            elif "fundingRate" in url:
                resp.json = lambda: [{"fundingRate": "0.0001"}]
            elif "openInterestHist" in url:
                resp.json = lambda: [
                    {"sumOpenInterest": "100000"},
                    {"sumOpenInterest": "101000"},
                ]
            else:
                resp.json = lambda: {}
            return resp

        mock_get.side_effect = fake_get

        result = self.scorer.compute_final_score()
        self.assertIn("raw_score", result)
        self.assertIn("probability", result)
        self.assertIn("direction", result)
        self.assertIn("confidence", result)
        self.assertIn("signals", result)

        self.assertIn(result["direction"], ("BUY_YES", "BUY_NO", "SKIP"))
        self.assertGreaterEqual(result["probability"], 0.0)
        self.assertLessEqual(result["probability"], 1.0)
        self.assertGreaterEqual(result["confidence"], 0.0)
        self.assertLessEqual(result["confidence"], 1.0)

        expected_signals = {
            "ema_cross", "rsi", "vwap", "volume_surge", "cvd",
            "orderbook", "funding_rate", "oi_change", "macro_momentum",
        }
        self.assertEqual(set(result["signals"].keys()), expected_signals)

    # ---- Helper internals -----------------------------------------------

    def test_sigmoid_range(self):
        from lib.direction_scorer import DirectionScorer
        for x in [-10, -3, -1, 0, 1, 3, 10]:
            p = DirectionScorer._sigmoid(x)
            self.assertGreater(p, 0.0)
            self.assertLess(p, 1.0)
        self.assertAlmostEqual(DirectionScorer._sigmoid(0), 0.5)

    def test_ema_helper(self):
        from lib.direction_scorer import DirectionScorer
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        ema = DirectionScorer._ema(values, 3)
        self.assertIsInstance(ema, float)
        self.assertGreater(ema, 0)

    def test_rsi_helper_overbought(self):
        from lib.direction_scorer import DirectionScorer
        # Continuously rising prices → RSI should approach 100
        closes = [float(i) for i in range(20)]
        rsi = DirectionScorer._rsi(closes, 14)
        self.assertGreater(rsi, 70)

    def test_rsi_helper_oversold(self):
        from lib.direction_scorer import DirectionScorer
        closes = [20.0 - float(i) for i in range(20)]
        rsi = DirectionScorer._rsi(closes, 14)
        self.assertLess(rsi, 30)

    def test_vwap_helper(self):
        from lib.direction_scorer import DirectionScorer
        klines = _make_klines(n=10, base_close=100.0, step=0.0)
        vwap = DirectionScorer._calc_vwap(klines)
        self.assertGreater(vwap, 0)

    def test_kline_cache(self):
        """Cached klines should be returned without a second HTTP call."""
        from lib.direction_scorer import DirectionScorer
        import time as time_mod

        scorer = DirectionScorer()
        klines = _make_klines(n=10)

        with patch("lib.direction_scorer.requests.get") as mock_get:
            resp = MagicMock()
            resp.raise_for_status = lambda: None
            resp.json = lambda: klines
            mock_get.return_value = resp

            result1 = scorer._get_klines("BTCUSDT", "1m", 10)
            result2 = scorer._get_klines("BTCUSDT", "1m", 10)

        self.assertEqual(result1, result2)
        self.assertEqual(mock_get.call_count, 1, "Second call should use cache")


if __name__ == "__main__":
    unittest.main()
