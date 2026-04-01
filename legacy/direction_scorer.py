"""
9维度BTC方向评分系统
从 Binance 公开 API 获取实时数据，计算加权评分，输出方向信号。
"""
import time
import math
import requests
import logging

log = logging.getLogger(__name__)

BINANCE_KLINE_URL = "https://api.binance.com/api/v3/klines"
BINANCE_TICKER_URL = "https://api.binance.com/api/v3/ticker/price"
BINANCE_FUNDING_URL = "https://fapi.binance.com/fapi/v1/fundingRate"
BINANCE_OI_URL = "https://fapi.binance.com/fapi/v1/openInterest"


class DirectionScorer:
    """
    综合多维度信号，输出5分钟BTC涨跌概率评分。
    信号权重配置：
      ema_cross:       0.15   # EMA交叉
      rsi_trend:       0.10   # RSI趋势
      vwap_position:   0.12   # VWAP位置
      volume_surge:    0.13   # 成交量突增方向
      cvd_direction:   0.18   # 累积量差（最重要）
      orderbook_ratio: 0.15   # 盘口深度比
      funding_rate:    0.07   # 资金费率
      oi_change:       0.05   # 持仓量变化
      macro_momentum:  0.05   # 宏观动量
    """

    WEIGHTS = {
        'ema_cross':       0.15,
        'rsi_trend':       0.10,
        'vwap_position':   0.12,
        'volume_surge':    0.13,
        'cvd_direction':   0.18,
        'orderbook_ratio': 0.15,
        'funding_rate':    0.07,
        'oi_change':       0.05,
        'macro_momentum':  0.05,
    }

    def __init__(self, steepness: float = 3.0, buy_threshold: float = 0.58,
                 sell_threshold: float = 0.42, cache_ttl: int = 10):
        self.steepness = steepness
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold
        self.cache_ttl = cache_ttl
        self._kline_cache = {}  # {key: (timestamp, data)}

    def _get_klines(self, symbol="BTCUSDT", interval="1m", limit=30):
        """从 Binance 获取K线数据，带缓存"""
        cache_key = f"{symbol}_{interval}_{limit}"
        now = time.time()
        if cache_key in self._kline_cache:
            ts, data = self._kline_cache[cache_key]
            if now - ts < self.cache_ttl:
                return data
        try:
            r = requests.get(BINANCE_KLINE_URL, params={
                "symbol": symbol, "interval": interval, "limit": limit
            }, timeout=5)
            r.raise_for_status()
            data = r.json()
            self._kline_cache[cache_key] = (now, data)
            return data
        except Exception as e:
            log.warning(f"Binance kline fetch failed: {e}")
            return []

    def _get_btc_price(self):
        try:
            r = requests.get(BINANCE_TICKER_URL, params={"symbol": "BTCUSDT"}, timeout=5)
            return float(r.json()["price"])
        except Exception as e:
            log.warning(f"BTC price fetch failed: {e}")
            return None

    def _get_funding_rate(self):
        try:
            r = requests.get(BINANCE_FUNDING_URL, params={"symbol": "BTCUSDT", "limit": 1}, timeout=5)
            data = r.json()
            if data:
                return float(data[-1]["fundingRate"])
        except Exception as e:
            log.warning(f"Funding rate fetch failed: {e}")
        return 0.0

    def _get_open_interest(self):
        try:
            r = requests.get(BINANCE_OI_URL, params={"symbol": "BTCUSDT"}, timeout=5)
            return float(r.json()["openInterest"])
        except Exception as e:
            log.warning(f"OI fetch failed: {e}")
        return None

    def _ema(self, values, period):
        if len(values) < period:
            return values[-1] if values else 0
        k = 2 / (period + 1)
        ema = values[0]
        for v in values[1:]:
            ema = v * k + ema * (1 - k)
        return ema

    def _rsi(self, closes, period=14):
        if len(closes) < period + 1:
            return 50.0
        gains, losses = [], []
        for i in range(1, len(closes)):
            diff = closes[i] - closes[i - 1]
            gains.append(max(diff, 0))
            losses.append(max(-diff, 0))
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def score_ema_cross(self, klines) -> float:
        """EMA(5) vs EMA(13) 1分钟K线"""
        if len(klines) < 14:
            return 0
        closes = [float(k[4]) for k in klines]
        ema_fast = self._ema(closes, 5)
        ema_slow = self._ema(closes, 13)
        prev_closes = closes[:-1]
        prev_fast = self._ema(prev_closes, 5)
        prev_slow = self._ema(prev_closes, 13)

        if ema_fast > ema_slow and prev_fast <= prev_slow:
            return 80    # 刚金叉
        elif ema_fast > ema_slow:
            gap = (ema_fast - ema_slow) / ema_slow * 100
            return min(60, gap * 20)
        elif ema_fast < ema_slow and prev_fast >= prev_slow:
            return -80   # 刚死叉
        elif ema_fast < ema_slow:
            gap = (ema_slow - ema_fast) / ema_slow * 100
            return max(-60, -gap * 20)
        return 0

    def score_rsi(self, klines) -> float:
        """RSI(14) 1分钟级别"""
        if len(klines) < 16:
            return 0
        closes = [float(k[4]) for k in klines]
        rsi = self._rsi(closes, 14)
        prev_rsi = self._rsi(closes[:-1], 14)
        direction = 1 if rsi > prev_rsi else -1

        if rsi > 70:
            return 50 * direction
        elif rsi > 55:
            return 40 * direction
        elif rsi < 30:
            return -50 * direction
        elif rsi < 45:
            return -40 * direction
        return 0

    def score_vwap(self, klines) -> float:
        """当前价相对VWAP位置"""
        if len(klines) < 5:
            return 0
        total_volume = 0
        total_vp = 0
        for k in klines:
            typical = (float(k[2]) + float(k[3]) + float(k[4])) / 3
            vol = float(k[5])
            total_vp += typical * vol
            total_volume += vol
        if total_volume == 0:
            return 0
        vwap = total_vp / total_volume
        current = float(klines[-1][4])
        deviation_pct = (current - vwap) / vwap * 100
        if deviation_pct > 0.1:
            return min(70, deviation_pct * 100)
        elif deviation_pct < -0.1:
            return max(-70, deviation_pct * 100)
        return 0

    def score_volume_surge(self, klines) -> float:
        """放量方向判断"""
        if len(klines) < 20:
            return 0
        volumes = [float(k[5]) for k in klines]
        avg_vol = sum(volumes[:-3]) / max(len(volumes) - 3, 1)
        recent_vol = sum(volumes[-3:]) / 3
        if avg_vol == 0:
            return 0
        vol_ratio = recent_vol / avg_vol
        price_change = float(klines[-1][4]) - float(klines[-4][4])
        if vol_ratio > 2.0:
            direction = 1 if price_change > 0 else -1
            return direction * min(80, vol_ratio * 25)
        return 0

    def score_cvd(self, klines) -> float:
        """CVD（累积成交量差）：主动买入量 - 主动卖出量"""
        if len(klines) < 10:
            return 0
        cvd = 0
        for k in klines[-10:]:
            o, h, l, c, vol = float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])
            rng = h - l
            if rng > 0:
                buy_ratio = (c - l) / rng
            else:
                buy_ratio = 0.5
            cvd += vol * (2 * buy_ratio - 1)
        # 标准化
        avg_vol = sum(float(k[5]) for k in klines[-10:]) / 10
        if avg_vol > 0:
            normalized = cvd / (avg_vol * 10) * 100
            return max(-90, min(90, normalized))
        return 0

    def score_orderbook(self, yes_depth: float = 0, no_depth: float = 0) -> float:
        """盘口买卖深度比（Polymarket YES vs NO）"""
        if no_depth == 0 and yes_depth == 0:
            return 0
        if no_depth == 0:
            return 50
        ratio = yes_depth / no_depth
        if ratio > 1.5:
            return min(70, (ratio - 1) * 80)
        elif ratio < 0.67:
            return max(-70, (ratio - 1) * 80)
        return 0

    def score_funding_rate(self) -> float:
        """资金费率信号"""
        rate = self._get_funding_rate()
        if 0.001 < rate <= 0.03:
            return 30
        elif rate > 0.05:
            return -20
        elif -0.03 <= rate < -0.001:
            return -30
        elif rate < -0.05:
            return 20
        return 0

    def score_oi_change(self, klines) -> float:
        """OI变化 + 价格变化组合"""
        # 简化：用5分钟价格变化方向 + 成交量变化作为OI代理
        if len(klines) < 10:
            return 0
        vol_recent = sum(float(k[5]) for k in klines[-5:])
        vol_prev = sum(float(k[5]) for k in klines[-10:-5])
        price_change = float(klines[-1][4]) - float(klines[-6][4])
        oi_proxy = (vol_recent - vol_prev) / max(vol_prev, 1) * 100

        if oi_proxy > 20 and price_change > 0:
            return 50
        elif oi_proxy > 20 and price_change < 0:
            return -50
        elif oi_proxy < -20 and price_change > 0:
            return 30
        elif oi_proxy < -20 and price_change < 0:
            return -30
        return 0

    def score_macro_momentum(self, klines) -> float:
        """5分钟和15分钟BTC收益方向"""
        if len(klines) < 15:
            return 0
        c5 = (float(klines[-1][4]) - float(klines[-6][4])) / float(klines[-6][4]) * 100
        c15 = (float(klines[-1][4]) - float(klines[-16][4])) / float(klines[-16][4]) * 100 if len(klines) >= 16 else 0

        if c5 > 0.03 and c15 > 0.03:
            return 70
        elif c5 < -0.03 and c15 < -0.03:
            return -70
        elif c5 > 0.03:
            return 30
        elif c5 < -0.03:
            return -30
        return 0

    def compute_final_score(self, yes_depth: float = 0, no_depth: float = 0) -> dict:
        """
        计算所有信号的加权总分并输出交易建议。
        Returns:
            {
                'total_score': float,
                'prob_up': float,        # sigmoid概率
                'direction': str,        # 'BUY_YES' | 'BUY_NO' | 'SKIP'
                'confidence': str,       # 'HIGH' | 'MEDIUM' | 'LOW'
                'signals': dict,         # 每个信号的详细得分
            }
        """
        klines = self._get_klines(limit=30)

        signals = {}
        signals['ema_cross'] = self.score_ema_cross(klines)
        signals['rsi_trend'] = self.score_rsi(klines)
        signals['vwap_position'] = self.score_vwap(klines)
        signals['volume_surge'] = self.score_volume_surge(klines)
        signals['cvd_direction'] = self.score_cvd(klines)
        signals['orderbook_ratio'] = self.score_orderbook(yes_depth, no_depth)
        signals['funding_rate'] = self.score_funding_rate()
        signals['oi_change'] = self.score_oi_change(klines)
        signals['macro_momentum'] = self.score_macro_momentum(klines)

        # 加权总分
        total = sum(signals[k] * self.WEIGHTS[k] for k in self.WEIGHTS)

        # Sigmoid 映射
        prob_up = 1 / (1 + math.exp(-total / (30 / self.steepness)))

        # 决策
        if prob_up > self.buy_threshold:
            direction = "BUY_YES"
            confidence = "HIGH" if prob_up > 0.65 else "MEDIUM"
        elif prob_up < self.sell_threshold:
            direction = "BUY_NO"
            confidence = "HIGH" if prob_up < 0.35 else "MEDIUM"
        else:
            direction = "SKIP"
            confidence = "LOW"

        return {
            'total_score': round(total, 2),
            'prob_up': round(prob_up, 4),
            'prob_down': round(1 - prob_up, 4),
            'direction': direction,
            'confidence': confidence,
            'signals': {k: round(v, 2) for k, v in signals.items()},
        }
