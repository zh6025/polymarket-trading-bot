"""
BTC price feed from Binance public API — no API key required.
"""
import logging
import requests
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

BINANCE_BASE = "https://api.binance.com"


def get_btc_klines(interval: str = "1m", limit: int = 30) -> List[List]:
    """
    Fetch BTC/USDT klines from Binance.

    Returns list of klines in Binance format:
    [open_time, open, high, low, close, volume, ...]
    Returns [] on error.
    """
    try:
        url = f"{BINANCE_BASE}/api/v3/klines"
        params = {"symbol": "BTCUSDT", "interval": interval, "limit": limit}
        resp = requests.get(url, params=params, timeout=8)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning(f"get_btc_klines failed: {exc}")
        return []


def get_btc_price() -> Optional[float]:
    """
    Fetch current BTC/USDT spot price from Binance ticker.

    Returns None on error.
    """
    try:
        url = f"{BINANCE_BASE}/api/v3/ticker/price"
        resp = requests.get(url, params={"symbol": "BTCUSDT"}, timeout=8)
        resp.raise_for_status()
        return float(resp.json()["price"])
    except Exception as exc:
        logger.warning(f"get_btc_price failed: {exc}")
        return None


def extract_closes(klines: List[List]) -> List[float]:
    """Extract close prices from klines."""
    return [float(k[4]) for k in klines]


def extract_volumes(klines: List[List]) -> List[float]:
    """Extract base volumes from klines."""
    return [float(k[5]) for k in klines]
