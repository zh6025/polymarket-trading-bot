"""
9-dimension direction scorer for 5-minute BTC binary markets.

Usage::

    scorer = DirectionScorer()
    signals = {
        'ema_cross': scorer.score_ema_cross(ema_fast, ema_slow, prev_fast, prev_slow),
        'rsi_trend': scorer.score_rsi(rsi, prev_rsi),
        ...
    }
    result = scorer.compute_final_score(signals)
    # result['action'] in {'BUY_YES', 'BUY_NO', 'SKIP'}
"""
import math
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class DirectionScorer:
    """
    Multi-dimension weighted scoring system for short-term BTC direction.

    Score range: [-100, +100]
    Positive → bullish (BUY_YES)   Negative → bearish (BUY_NO)
    """

    def __init__(self, sigmoid_scale: float = 30.0):
        self.sigmoid_scale = sigmoid_scale
        self.weights: Dict[str, float] = {
            "ema_cross": 0.15,
            "rsi_trend": 0.10,
            "vwap_position": 0.12,
            "volume_surge": 0.13,
            "cvd_direction": 0.18,
            "orderbook_ratio": 0.15,
            "funding_rate": 0.07,
            "oi_change": 0.05,
            "macro_sentiment": 0.05,
        }

    # ------------------------------------------------------------------
    # Individual signal scorers (each returns a raw score in [-100, 100])
    # ------------------------------------------------------------------

    def score_ema_cross(
        self,
        ema_fast: float,
        ema_slow: float,
        prev_ema_fast: float,
        prev_ema_slow: float,
    ) -> float:
        """EMA(fast) vs EMA(slow) crossover — default EMA(3)/EMA(8)."""
        if ema_fast > ema_slow and prev_ema_fast <= prev_ema_slow:
            return 80.0   # fresh golden cross
        if ema_fast > ema_slow:
            gap_pct = (ema_fast - ema_slow) / max(ema_slow, 1e-9) * 100
            return min(60.0, gap_pct * 20)
        if ema_fast < ema_slow and prev_ema_fast >= prev_ema_slow:
            return -80.0  # fresh death cross
        if ema_fast < ema_slow:
            gap_pct = (ema_slow - ema_fast) / max(ema_slow, 1e-9) * 100
            return max(-60.0, -gap_pct * 20)
        return 0.0

    def score_rsi(self, rsi_value: float, rsi_prev: float) -> float:
        """
        RSI(14) momentum/contrarian signal.

        Overbought (>70): momentum continuation if rising, potential reversal if falling.
        Oversold (<30): contrarian bounce expected — falling further strengthens the
        reversal thesis (positive score); already bouncing reduces the edge (negative score).
        """
        direction = 1.0 if rsi_value > rsi_prev else -1.0
        if rsi_value > 70:
            return 50.0 * direction
        if rsi_value > 55:
            return 40.0 * direction
        if rsi_value < 30:
            # Contrarian: oversold + falling deeper → higher reversal probability (+score)
            # Oversold + already bouncing → reversal in progress, less edge (-score)
            return -50.0 * direction
        if rsi_value < 45:
            return -40.0 * direction
        return 0.0

    def score_vwap(self, current_price: float, vwap: float) -> float:
        """Price position relative to VWAP."""
        if vwap <= 0:
            return 0.0
        deviation_pct = (current_price - vwap) / vwap * 100
        if deviation_pct > 0.1:
            return min(70.0, deviation_pct * 100)
        if deviation_pct < -0.1:
            return max(-70.0, deviation_pct * 100)
        return 0.0

    def score_volume_surge(
        self, current_vol: float, avg_vol: float, price_change: float
    ) -> float:
        """Volume surge in direction of price move."""
        if avg_vol <= 0:
            return 0.0
        vol_ratio = current_vol / avg_vol
        if vol_ratio > 2.0:
            direction = 1.0 if price_change > 0 else -1.0
            return direction * min(80.0, vol_ratio * 25)
        return 0.0

    def score_cvd(self, cvd_5min_change: float) -> float:
        """
        CVD (Cumulative Volume Delta) = active buy vol − active sell vol.
        Most important short-term signal.
        """
        if cvd_5min_change > 0:
            return min(90.0, cvd_5min_change * 10)
        return max(-90.0, cvd_5min_change * 10)

    def score_orderbook(self, bid_depth: float, ask_depth: float) -> float:
        """Order book bid/ask depth ratio."""
        if ask_depth <= 0:
            return 50.0
        ratio = bid_depth / ask_depth
        if ratio > 1.5:
            return min(70.0, (ratio - 1) * 80)
        if ratio < 0.67:
            return max(-70.0, (ratio - 1) * 80)
        return 0.0

    def score_funding_rate(self, funding_rate: float) -> float:
        """
        Funding rate sentiment.
        Moderate positive → bullish; extreme positive → overheated (bearish).
        """
        if 0.001 < funding_rate <= 0.03:
            return 30.0
        if funding_rate > 0.05:
            return -20.0
        if -0.03 <= funding_rate < -0.001:
            return -30.0
        if funding_rate < -0.05:
            return 20.0
        return 0.0

    def score_oi_change(self, oi_change_pct: float, price_change: float) -> float:
        """Open Interest change combined with price direction."""
        if oi_change_pct > 2 and price_change > 0:
            return 50.0
        if oi_change_pct > 2 and price_change < 0:
            return -50.0
        if oi_change_pct < -2 and price_change > 0:
            return 30.0
        if oi_change_pct < -2 and price_change < 0:
            return -30.0
        return 0.0

    # ------------------------------------------------------------------
    # Final aggregation
    # ------------------------------------------------------------------

    def compute_final_score(self, signals: Dict[str, float]) -> Dict[str, Any]:
        """
        Aggregate raw signal scores with weights, output decision.

        ``signals`` is a dict mapping signal name → raw score ([-100, 100]).
        Missing signals contribute 0.

        Returns::

            {
                'total_score': float,
                'prob_up': float,
                'prob_down': float,
                'action': 'BUY_YES' | 'BUY_NO' | 'SKIP',
                'confidence': 'HIGH' | 'MEDIUM' | 'LOW',
                'details': {signal: {'raw', 'weight', 'weighted'}},
            }
        """
        total_score = 0.0
        details: Dict[str, Any] = {}

        for signal_name, weight in self.weights.items():
            raw_score = signals.get(signal_name, 0.0)
            weighted = raw_score * weight
            total_score += weighted
            details[signal_name] = {
                "raw": raw_score,
                "weight": weight,
                "weighted": round(weighted, 4),
            }

        # Sigmoid probability
        prob_up = 1.0 / (1.0 + math.exp(-total_score / self.sigmoid_scale))

        if total_score > 25:
            action, confidence = "BUY_YES", "HIGH"
        elif total_score > 10:
            action, confidence = "BUY_YES", "MEDIUM"
        elif total_score < -25:
            action, confidence = "BUY_NO", "HIGH"
        elif total_score < -10:
            action, confidence = "BUY_NO", "MEDIUM"
        else:
            action, confidence = "SKIP", "LOW"

        return {
            "total_score": round(total_score, 4),
            "prob_up": round(prob_up, 4),
            "prob_down": round(1.0 - prob_up, 4),
            "action": action,
            "confidence": confidence,
            "details": details,
        }
