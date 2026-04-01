"""
MarketData: Market data snapshots and BTC real-time data interface.
Handles Polymarket orderbook snapshots and BTC price data from Binance.
"""
import time
import logging
import requests
from dataclasses import dataclass
from typing import Optional, Dict, Any

log = logging.getLogger(__name__)

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
BINANCE_TICKER_URL = "https://api.binance.com/api/v3/ticker/price"


@dataclass
class OrderbookSnapshot:
    """Snapshot of Polymarket orderbook for a token"""
    token_id: str
    timestamp: float
    best_bid: Optional[float]
    best_ask: Optional[float]
    mid_price: Optional[float]
    bid_depth: float   # total bid size
    ask_depth: float   # total ask size
    spread: Optional[float]

    @property
    def is_valid(self) -> bool:
        return self.mid_price is not None and self.mid_price > 0

    @property
    def price(self) -> Optional[float]:
        return self.mid_price


@dataclass
class BtcSnapshot:
    """BTC price snapshot from Binance"""
    timestamp: float
    price: float
    # Optional 5m kline data
    open_5m: Optional[float] = None
    close_5m: Optional[float] = None
    high_5m: Optional[float] = None
    low_5m: Optional[float] = None
    volume_5m: Optional[float] = None
    # Historical reference prices
    price_15m_ago: Optional[float] = None
    price_5m_ago: Optional[float] = None

    @property
    def momentum_5m(self) -> Optional[float]:
        """5m price change as fraction"""
        if self.price_5m_ago and self.price_5m_ago > 0:
            return (self.price - self.price_5m_ago) / self.price_5m_ago
        return None

    @property
    def momentum_15m(self) -> Optional[float]:
        """15m price change as fraction"""
        if self.price_15m_ago and self.price_15m_ago > 0:
            return (self.price - self.price_15m_ago) / self.price_15m_ago
        return None


class MarketDataFetcher:
    """Fetches and caches market data"""

    def __init__(self):
        self._btc_cache: Optional[BtcSnapshot] = None
        self._btc_cache_time: float = 0.0
        self._btc_cache_ttl: float = 10.0  # seconds

    def get_btc_snapshot(self, force_refresh: bool = False) -> Optional[BtcSnapshot]:
        """Get current BTC price snapshot from Binance"""
        now = time.time()
        if not force_refresh and self._btc_cache and (now - self._btc_cache_time) < self._btc_cache_ttl:
            return self._btc_cache

        try:
            resp = requests.get(BINANCE_TICKER_URL, params={"symbol": "BTCUSDT"}, timeout=5)
            resp.raise_for_status()
            current_price = float(resp.json()["price"])

            # Get last 4 × 5m candles for historical context (~20 min)
            klines_resp = requests.get(BINANCE_KLINES_URL, params={
                "symbol": "BTCUSDT",
                "interval": "5m",
                "limit": 4,
            }, timeout=5)
            klines_resp.raise_for_status()
            klines = klines_resp.json()

            snapshot = BtcSnapshot(timestamp=now, price=current_price)

            if len(klines) >= 4:
                # klines: [open_time, open, high, low, close, volume, ...]
                snapshot.price_15m_ago = float(klines[0][4])  # close 3 candles ago
                snapshot.price_5m_ago = float(klines[2][4])   # close 1 candle ago
                latest = klines[3]
                snapshot.open_5m = float(latest[1])
                snapshot.high_5m = float(latest[2])
                snapshot.low_5m = float(latest[3])
                snapshot.close_5m = float(latest[4])
                snapshot.volume_5m = float(latest[5])
            elif len(klines) >= 2:
                snapshot.price_5m_ago = float(klines[-2][4])

            self._btc_cache = snapshot
            self._btc_cache_time = now
            log.debug(f"BTC snapshot: ${current_price:.2f}")
            return snapshot

        except Exception as e:
            log.warning(f"Failed to fetch BTC snapshot: {e}")
            return None

    def get_orderbook_snapshot(self, polymarket_client, token_id: str) -> Optional[OrderbookSnapshot]:
        """Get Polymarket orderbook snapshot for a token"""
        try:
            book = polymarket_client.get_orderbook(token_id)
            prices = polymarket_client.calculate_mid_price(book)

            bids = book.get('bids', [])
            asks = book.get('asks', [])
            bid_depth = sum(float(b.get('size', 0)) for b in bids)
            ask_depth = sum(float(a.get('size', 0)) for a in asks)

            best_bid = prices.get('bid')
            best_ask = prices.get('ask')
            mid = prices.get('mid')
            spread = (best_ask - best_bid) if (best_bid and best_ask) else None

            return OrderbookSnapshot(
                token_id=token_id,
                timestamp=time.time(),
                best_bid=best_bid,
                best_ask=best_ask,
                mid_price=mid,
                bid_depth=bid_depth,
                ask_depth=ask_depth,
                spread=spread,
            )
        except Exception as e:
            log.warning(f"Failed to fetch orderbook snapshot for {token_id}: {e}")
            return None

    def get_recent_price_change(self, seconds: int = 10) -> Optional[float]:
        """
        Approximate absolute price change fraction over the last N seconds.
        Uses cached BTC snapshot's open_5m vs current price.
        Returns None if data is unavailable or too old.
        """
        now = time.time()
        if self._btc_cache and (now - self._btc_cache_time) < seconds:
            snap = self._btc_cache
            if snap.open_5m and snap.price and snap.open_5m > 0:
                return abs(snap.price - snap.open_5m) / snap.open_5m
        return None
