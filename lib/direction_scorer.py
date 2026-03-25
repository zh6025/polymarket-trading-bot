"""
lib/direction_scorer.py — 9-Dimension DirectionScorer

Fetches real BTC market data from Binance public REST API and computes a
weighted score across 9 dimensions to produce a direction signal.
"""
import time
import math
from typing import Dict, List, Optional, Any

import requests

from lib.utils import log_info, log_error, log_warn

# ---------------------------------------------------------------------------
# Binance public REST endpoints (no API key required)
# ---------------------------------------------------------------------------
_BINANCE_BASE = "https://api.binance.com"
_BINANCE_FAPI = "https://fapi.binance.com"
_REQUEST_TIMEOUT = 5  # seconds
_KLINE_CACHE_TTL = 10  # seconds — avoid hammering the API

# Normalisation caps for individual signals
_EMA_CROSS_NORM  = 0.005   # 0.5 % distance between EMAs → score ±1
_VWAP_NORM       = 0.01    # 1.0 % distance from VWAP → score ±1
_FUNDING_RATE_CAP = 0.002  # ±0.2 % funding rate per 8 h → score ±1
_OI_CHANGE_NORM  = 0.01    # 1.0 % OI change → score ±1
_MACRO_MOM_CAP   = 0.01    # 1.0 % return → score ±1


class DirectionScorer:
    """
    Fetches BTC market data and computes a weighted composite score across
    9 dimensions.  Returns a final signal: BUY_YES | BUY_NO | SKIP.

    Parameters
    ----------
    steepness : float
        Sigmoid steepness k.  probability = sigmoid(raw_score * k).
    buy_threshold : float
        probability > buy_threshold → BUY_YES (default 0.58).
    sell_threshold : float
        probability < sell_threshold → BUY_NO (default 0.42).
    polymarket_client : optional
        Injected PolymarketClient instance used for orderbook signal.
        When None the orderbook signal returns 0.
    yes_token_id : str | None
        YES-side token ID for the Polymarket orderbook depth signal.
    no_token_id : str | None
        NO-side token ID for the Polymarket orderbook depth signal.
    """

    # Signal weights (must sum to 1.0)
    _WEIGHTS: Dict[str, float] = {
        "ema_cross":       0.20,
        "rsi":             0.10,
        "vwap":            0.10,
        "volume_surge":    0.10,
        "cvd":             0.15,
        "orderbook":       0.10,
        "funding_rate":    0.05,
        "oi_change":       0.05,
        "macro_momentum":  0.15,
    }

    def __init__(
        self,
        steepness: float = 3.0,
        buy_threshold: float = 0.58,
        sell_threshold: float = 0.42,
        polymarket_client=None,
        yes_token_id: Optional[str] = None,
        no_token_id: Optional[str] = None,
    ):
        self.steepness = steepness
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold
        self.polymarket_client = polymarket_client
        self.yes_token_id = yes_token_id
        self.no_token_id = no_token_id

        # kline cache  {interval: (fetch_time, data)}
        self._kline_cache: Dict[str, tuple] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_final_score(self) -> Dict[str, Any]:
        """
        Compute all 9 signals and return a dict with:
          raw_score, probability, direction, confidence, signals
        """
        klines_1m = self._get_klines("BTCUSDT", "1m", 30)
        klines_5m = self._get_klines("BTCUSDT", "5m", 20)
        klines_15m = self._get_klines("BTCUSDT", "15m", 10)
        current_price = self._get_current_price("BTCUSDT")

        signals: Dict[str, float] = {
            "ema_cross":      self.score_ema_cross(klines_1m),
            "rsi":            self.score_rsi(klines_1m),
            "vwap":           self.score_vwap(klines_1m, current_price),
            "volume_surge":   self.score_volume_surge(klines_1m),
            "cvd":            self.score_cvd(klines_1m),
            "orderbook":      self.score_orderbook(),
            "funding_rate":   self.score_funding_rate(),
            "oi_change":      self.score_oi_change(current_price),
            "macro_momentum": self.score_macro_momentum(klines_5m, klines_15m),
        }

        raw_score: float = sum(
            self._WEIGHTS[name] * value for name, value in signals.items()
        )

        probability = self._sigmoid(raw_score * self.steepness)
        confidence = abs(probability - 0.5) * 2

        if probability > self.buy_threshold:
            direction = "BUY_YES"
        elif probability < self.sell_threshold:
            direction = "BUY_NO"
        else:
            direction = "SKIP"

        result = {
            "raw_score": raw_score,
            "probability": probability,
            "direction": direction,
            "confidence": confidence,
            "signals": signals,
        }
        log_info(
            f"[Scorer] direction={direction} prob={probability:.4f} "
            f"conf={confidence:.4f} raw={raw_score:.4f}"
        )
        log_info(f"[Scorer] signals={signals}")
        return result

    # ------------------------------------------------------------------
    # Individual signal scorers
    # ------------------------------------------------------------------

    def score_ema_cross(self, klines: List[List]) -> float:
        """EMA-3 vs EMA-8 crossover on 1-min candles. Returns [-1, 1]."""
        try:
            closes = self._closes(klines)
            if len(closes) < 9:
                return 0.0
            ema_fast = self._ema(closes, 3)
            ema_slow = self._ema(closes, 8)
            if ema_slow == 0:
                return 0.0
            distance = (ema_fast - ema_slow) / ema_slow
            # normalise: cap at ±0.5 % → score ±1
            score = distance / _EMA_CROSS_NORM
            return max(-1.0, min(1.0, score))
        except Exception as exc:
            log_warn(f"[Scorer] score_ema_cross failed: {exc}")
            return 0.0

    def score_rsi(self, klines: List[List]) -> float:
        """RSI(14) on 1-min candles. Returns [-1, 1]."""
        try:
            closes = self._closes(klines)
            if len(closes) < 15:
                return 0.0
            rsi = self._rsi(closes, 14)
            if rsi > 55:
                # scale 55..100 → 0..1
                return min(1.0, (rsi - 55) / 45)
            elif rsi < 45:
                # scale 45..0 → 0..-1
                return max(-1.0, (rsi - 45) / 45)
            else:
                # 45–55 → linear around 0
                return (rsi - 50) / 5 * 0.1
        except Exception as exc:
            log_warn(f"[Scorer] score_rsi failed: {exc}")
            return 0.0

    def score_vwap(self, klines: List[List], current_price: Optional[float]) -> float:
        """Current price vs session VWAP. Returns [-1, 1]."""
        try:
            if not current_price or not klines:
                return 0.0
            vwap = self._calc_vwap(klines)
            if vwap <= 0:
                return 0.0
            pct = (current_price - vwap) / vwap
            # cap at ±1 % → score ±1
            score = pct / _VWAP_NORM
            return max(-1.0, min(1.0, score))
        except Exception as exc:
            log_warn(f"[Scorer] score_vwap failed: {exc}")
            return 0.0

    def score_volume_surge(self, klines: List[List]) -> float:
        """Compare last 3 candles volume vs 20-candle avg. Returns [-1, 1]."""
        try:
            if len(klines) < 20:
                return 0.0
            volumes = [float(k[5]) for k in klines]
            avg_vol = sum(volumes[-20:]) / 20
            if avg_vol <= 0:
                return 0.0
            last3_avg = sum(volumes[-3:]) / 3
            surge_ratio = last3_avg / avg_vol
            if surge_ratio < 1.5:
                return 0.0  # no meaningful surge
            # direction = last candle bullish?
            last = klines[-1]
            close, open_ = float(last[4]), float(last[1])
            direction = 1.0 if close > open_ else -1.0
            magnitude = min(1.0, (surge_ratio - 1) / 2)
            return direction * magnitude
        except Exception as exc:
            log_warn(f"[Scorer] score_volume_surge failed: {exc}")
            return 0.0

    def score_cvd(self, klines: List[List]) -> float:
        """Cumulative Volume Delta (proxy) over last 10 candles. Returns [-1, 1]."""
        try:
            if len(klines) < 10:
                return 0.0
            cvd = 0.0
            total_vol = 0.0
            for k in klines[-10:]:
                open_, close = float(k[1]), float(k[4])
                high, low = float(k[2]), float(k[3])
                volume = float(k[5])
                bar_range = high - low
                if bar_range > 0:
                    buy_pct = (close - low) / bar_range
                else:
                    buy_pct = 0.5
                delta = (buy_pct - 0.5) * 2 * volume  # [-vol, +vol]
                cvd += delta
                total_vol += volume
            if total_vol <= 0:
                return 0.0
            score = cvd / total_vol  # normalised to [-1, 1]
            return max(-1.0, min(1.0, score))
        except Exception as exc:
            log_warn(f"[Scorer] score_cvd failed: {exc}")
            return 0.0

    def score_orderbook(self) -> float:
        """Polymarket YES vs NO depth ratio. Returns [-1, 1]."""
        try:
            if not self.polymarket_client or not self.yes_token_id or not self.no_token_id:
                return 0.0
            yes_depth = self._polymarket_depth(self.yes_token_id)
            no_depth = self._polymarket_depth(self.no_token_id)
            total = yes_depth + no_depth
            if total <= 0:
                return 0.0
            # imbalance in [-1, 1]
            return (yes_depth - no_depth) / total
        except Exception as exc:
            log_warn(f"[Scorer] score_orderbook failed: {exc}")
            return 0.0

    def score_funding_rate(self) -> float:
        """
        BTC perp funding rate from Binance.
        Positive funding (longs paying) → slight bearish → negative score.
        Returns [-1, 1].
        """
        try:
            url = f"{_BINANCE_FAPI}/fapi/v1/fundingRate"
            params = {"symbol": "BTCUSDT", "limit": 1}
            resp = requests.get(url, params=params, timeout=_REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            if not data:
                return 0.0
            rate = float(data[-1]["fundingRate"])
            # Cap at ±0.2 % per 8 h → score ±1
            score = -(rate / _FUNDING_RATE_CAP)
            return max(-1.0, min(1.0, score))
        except Exception as exc:
            log_warn(f"[Scorer] score_funding_rate failed: {exc}")
            return 0.0

    def score_oi_change(self, current_price: Optional[float]) -> float:
        """
        BTC open interest change over last 5 min from Binance futures.
        Rising OI + rising price → bullish → positive.
        Returns [-1, 1].
        """
        try:
            url = f"{_BINANCE_FAPI}/fapi/v1/openInterestHist"
            params = {"symbol": "BTCUSDT", "period": "5m", "limit": 2}
            resp = requests.get(url, params=params, timeout=_REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            if len(data) < 2:
                return 0.0
            oi_old = float(data[0]["sumOpenInterest"])
            oi_new = float(data[1]["sumOpenInterest"])
            if oi_old <= 0:
                return 0.0
            oi_change_pct = (oi_new - oi_old) / oi_old  # e.g. 0.005 = +0.5 %

            # We also need a price direction hint
            price_signal = 0.0
            if current_price:
                # Use last two 5-min klines for price direction
                klines = self._get_klines("BTCUSDT", "5m", 3)
                if len(klines) >= 2:
                    prev_close = float(klines[-2][4])
                    last_close = float(klines[-1][4])
                    price_signal = 1.0 if last_close > prev_close else -1.0

            # Rising OI confirms the price direction (bullish or bearish)
            magnitude = min(1.0, abs(oi_change_pct) / _OI_CHANGE_NORM)
            if oi_change_pct > 0:
                return price_signal * magnitude
            else:
                return -price_signal * magnitude
        except Exception as exc:
            log_warn(f"[Scorer] score_oi_change failed: {exc}")
            return 0.0

    def score_macro_momentum(
        self,
        klines_5m: List[List],
        klines_15m: List[List],
    ) -> float:
        """5-min and 15-min BTC returns. Returns [-1, 1]."""
        try:
            ret5 = self._last_return(klines_5m)
            ret15 = self._last_return(klines_15m)

            # Both positive → strong positive; both negative → strong negative
            # Mixed → weak
            if ret5 > 0 and ret15 > 0:
                score = 1.0
            elif ret5 < 0 and ret15 < 0:
                score = -1.0
            elif ret5 == 0 and ret15 == 0:
                score = 0.0
            else:
                # mixed signals — weight recent more
                score = (ret5 * 2 + ret15) / 3
                # normalise
                score = max(-1.0, min(1.0, score / _MACRO_MOM_CAP))

            return score
        except Exception as exc:
            log_warn(f"[Scorer] score_macro_momentum failed: {exc}")
            return 0.0

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _sigmoid(x: float) -> float:
        return 1.0 / (1.0 + math.exp(-x))

    @staticmethod
    def _closes(klines: List[List]) -> List[float]:
        return [float(k[4]) for k in klines]

    @staticmethod
    def _ema(values: List[float], period: int) -> float:
        """Exponential Moving Average of the last N values."""
        if len(values) < period:
            return sum(values) / len(values)
        k = 2.0 / (period + 1)
        ema = values[0]
        for v in values[1:]:
            ema = v * k + ema * (1 - k)
        return ema

    @staticmethod
    def _rsi(closes: List[float], period: int) -> float:
        gains, losses = [], []
        for i in range(1, len(closes)):
            diff = closes[i] - closes[i - 1]
            gains.append(max(0, diff))
            losses.append(max(0, -diff))
        if len(gains) < period:
            return 50.0
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - 100 / (1 + rs)

    @staticmethod
    def _calc_vwap(klines: List[List]) -> float:
        total_tpv = 0.0
        total_vol = 0.0
        for k in klines:
            high, low, close = float(k[2]), float(k[3]), float(k[4])
            volume = float(k[5])
            typical = (high + low + close) / 3
            total_tpv += typical * volume
            total_vol += volume
        return total_tpv / total_vol if total_vol > 0 else 0.0

    @staticmethod
    def _last_return(klines: List[List]) -> float:
        if len(klines) < 2:
            return 0.0
        prev_close = float(klines[-2][4])
        last_close = float(klines[-1][4])
        if prev_close <= 0:
            return 0.0
        return (last_close - prev_close) / prev_close

    def _get_klines(self, symbol: str, interval: str, limit: int) -> List[List]:
        """Fetch klines with 10-second cache."""
        cache_key = f"{symbol}_{interval}_{limit}"
        cached = self._kline_cache.get(cache_key)
        if cached:
            ts, data = cached
            if time.time() - ts < _KLINE_CACHE_TTL:
                return data
        try:
            url = f"{_BINANCE_BASE}/api/v3/klines"
            params = {"symbol": symbol, "interval": interval, "limit": limit}
            resp = requests.get(url, params=params, timeout=_REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            self._kline_cache[cache_key] = (time.time(), data)
            return data
        except Exception as exc:
            log_warn(f"[Scorer] _get_klines({symbol},{interval}) failed: {exc}")
            return cached[1] if cached else []

    def _get_current_price(self, symbol: str) -> Optional[float]:
        """Fetch current spot price."""
        try:
            url = f"{_BINANCE_BASE}/api/v3/ticker/price"
            resp = requests.get(url, params={"symbol": symbol}, timeout=_REQUEST_TIMEOUT)
            resp.raise_for_status()
            return float(resp.json()["price"])
        except Exception as exc:
            log_warn(f"[Scorer] _get_current_price failed: {exc}")
            return None

    def _polymarket_depth(self, token_id: str) -> float:
        """Sum of top-of-book USDC depth for a token."""
        try:
            book = self.polymarket_client.get_orderbook(token_id)
            bids = book.get("bids", [])
            asks = book.get("asks", [])
            depth = 0.0
            for order in bids[:5] + asks[:5]:
                price = float(order.get("price", 0))
                size = float(order.get("size", 0))
                depth += price * size
            return depth
        except Exception as exc:
            log_warn(f"[Scorer] _polymarket_depth failed: {exc}")
            return 0.0
