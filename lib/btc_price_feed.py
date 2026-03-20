import requests
from lib.utils import log_info, log_error

# Binance 公共 API（无需 API Key）
# Binance public API endpoints (no API key required)
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
BINANCE_TICKER_URL = "https://api.binance.com/api/v3/ticker/price"


class BtcPriceFeed:
    """
    从 Binance 公共 REST API 获取 BTC/USDT 实时价格和 K 线数据。
    Fetches BTC/USDT real-time price and OHLCV candles from Binance's public REST API.
    No API key is required.
    """

    def __init__(self, timeout: int = 10):
        self.timeout = timeout

    def get_btc_klines(self, interval: str = "1m", limit: int = 30):
        """
        获取最近 N 根 K 线（默认1分钟K线，共30根）。
        Fetch recent BTC/USDT candlestick data.

        Returns list of candles: [open_time, open, high, low, close, volume, ...]
        Returns empty list on error.
        """
        params = {
            "symbol": "BTCUSDT",
            "interval": interval,
            "limit": limit,
        }
        try:
            resp = requests.get(BINANCE_KLINES_URL, params=params, timeout=self.timeout)
            resp.raise_for_status()
            klines = resp.json()
            log_info(f"📥 获取到 {len(klines)} 根 BTC {interval} K线数据")
            return klines
        except requests.RequestException as e:
            log_error(f"❌ 获取 BTC K线失败: {e}")
            return []

    def get_btc_price(self) -> float:
        """
        获取 BTC/USDT 当前价格。
        Fetch the current BTC/USDT spot price.

        Returns current price as float, or 0.0 on error.
        """
        params = {"symbol": "BTCUSDT"}
        try:
            resp = requests.get(BINANCE_TICKER_URL, params=params, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            price = float(data["price"])
            log_info(f"💰 当前 BTC 价格: ${price:,.2f}")
            return price
        except (requests.RequestException, KeyError, ValueError) as e:
            log_error(f"❌ 获取 BTC 价格失败: {e}")
            return 0.0
