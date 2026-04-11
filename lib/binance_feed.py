"""
BinanceFeed: 从Binance获取BTC/USDT实时价格
- get_btc_price(): 获取实时价格（带5秒缓存）
- get_recent_prices(seconds): 获取最近N秒的价格序列
- get_momentum(seconds): 计算最近N秒的动量方向和强度
- 内部维护一个价格历史ring buffer（最多保留600秒=10分钟）
"""
import time
import logging
from collections import deque
from typing import List, Optional, Tuple

import requests

log = logging.getLogger(__name__)

BINANCE_TICKER_URL = "https://api.binance.com/api/v3/ticker/price"
CACHE_TTL_SEC = 5
MAX_HISTORY_SEC = 600


class BinanceFeed:
    """Binance BTC/USDT 实时价格数据源"""

    def __init__(self, symbol: str = "BTCUSDT"):
        self.symbol = symbol
        # ring buffer: 每项为 (timestamp, price)
        self._history: deque = deque()
        self._cached_price: Optional[float] = None
        self._cache_ts: float = 0.0

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def get_btc_price(self) -> Optional[float]:
        """从Binance获取BTC/USDT实时价格（带5秒缓存），并追加到历史"""
        now = time.time()
        if self._cached_price is not None and (now - self._cache_ts) < CACHE_TTL_SEC:
            return self._cached_price

        price = self._fetch_price()
        if price is not None:
            self._cached_price = price
            self._cache_ts = now
            self._append_history(now, price)
        return price

    def get_recent_prices(self, seconds: int = 30) -> List[float]:
        """获取最近N秒的价格序列（时间升序）"""
        cutoff = time.time() - seconds
        return [p for ts, p in self._history if ts >= cutoff]

    def get_momentum(self, seconds: int = 30) -> dict:
        """
        计算最近N秒的动量方向和强度。
        返回:
            {
                'direction': 'UP' | 'DOWN' | 'FLAT',
                'delta': float,          # 绝对变化（USDT）
                'delta_bps': float,      # 相对变化（基点, 1bps = 0.01%）
                'n_samples': int,
            }
        """
        prices = self.get_recent_prices(seconds)
        if len(prices) < 2:
            return {'direction': 'FLAT', 'delta': 0.0, 'delta_bps': 0.0, 'n_samples': len(prices)}

        first, last = prices[0], prices[-1]
        delta = last - first
        delta_bps = delta / first * 10_000 if first > 0 else 0.0
        direction = 'UP' if delta > 0 else ('DOWN' if delta < 0 else 'FLAT')

        return {
            'direction': direction,
            'delta': delta,
            'delta_bps': delta_bps,
            'n_samples': len(prices),
        }

    def inject_price(self, price: float, ts: Optional[float] = None):
        """手动注入价格（供测试/回测使用）"""
        now = ts if ts is not None else time.time()
        self._cached_price = price
        self._cache_ts = now
        self._append_history(now, price)

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _fetch_price(self) -> Optional[float]:
        try:
            resp = requests.get(
                BINANCE_TICKER_URL,
                params={"symbol": self.symbol},
                timeout=5,
            )
            if resp.status_code == 200:
                data = resp.json()
                return float(data["price"])
            log.warning(f"Binance API 返回 {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            log.error(f"获取Binance价格失败: {e}")
        return None

    def _append_history(self, ts: float, price: float):
        self._history.append((ts, price))
        # 清理超过10分钟的旧数据
        cutoff = ts - MAX_HISTORY_SEC
        while self._history and self._history[0][0] < cutoff:
            self._history.popleft()
