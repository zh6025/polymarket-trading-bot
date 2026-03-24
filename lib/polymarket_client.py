import time
from typing import Dict, List, Optional, Any

import requests

from lib.utils import APIClient, log_error, log_info


class PolymarketClient:
    """Polymarket API Client for market data and simplified trading hooks."""

    def __init__(
        self,
        host: str = "https://clob.polymarket.com",
        chain_id: int = 137,
        private_key: str = "",
        proxy_address: str = "",
    ):
        self.host = host.rstrip("/")
        self.chain_id = chain_id
        self.private_key = private_key
        self.proxy_address = proxy_address
        self.client = APIClient(base_url=self.host)

    def get_markets(self) -> List[Dict[str, Any]]:
        try:
            url = f"{self.host}/markets"
            log_info("Fetching markets from CLOB")
            response = self.client.get(url)
            markets = response if isinstance(response, list) else response.get("data", [])
            log_info(f"Found {len(markets)} markets")
            return markets
        except Exception as e:
            log_error(f"Failed to fetch markets: {e}")
            return []

    def filter_btc_markets(self, markets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        btc_markets = [
            m
            for m in markets
            if m and ("BTC" in m.get("question", "").upper() or "BITCOIN" in m.get("question", "").upper())
        ]
        log_info(f"Found {len(btc_markets)} BTC markets")
        return btc_markets

    def get_order_book(self, token_id: str) -> Dict[str, Any]:
        try:
            url = f"{self.host}/book?token_id={token_id}"
            log_info(f"Fetching orderbook for token_id={token_id}")
            response = self.client.get(url)
            return response
        except Exception as e:
            log_error(f"Failed to fetch orderbook: {e}")
            raise

    def get_orderbook(self, token_id: str) -> Dict[str, Any]:
        return self.get_order_book(token_id)

    def get_btc_5m_market_by_slug(self, slug: str) -> Optional[Dict[str, Any]]:
        try:
            url = f"https://gamma-api.polymarket.com/events/slug/{slug}"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data and isinstance(data, dict):
                    return data
            return None
        except Exception as e:
            log_error(f"Failed to fetch market by slug: {e}")
            return None

    def get_current_btc_5m_market(self) -> Optional[Dict[str, Any]]:
        now = int(time.time())
        for offset in [0, 300, -300]:
            nearest_5min = (now + offset) - ((now + offset) % 300)
            slug = f"btc-updown-5m-{nearest_5min}"
            log_info(f"Trying market slug: {slug}")
            event = self.get_btc_5m_market_by_slug(slug)
            if event:
                markets = event.get("markets", [])
                active = [m for m in markets if m.get("acceptingOrders", False) and not m.get("closed", True)]
                if active:
                    log_info(f"Found active market: {event.get('title', slug)}")
                    return event
        return None

    def calculate_mid_price(self, book: Dict[str, Any]) -> Dict[str, float]:
        try:
            bids = book.get("bids", [])
            asks = book.get("asks", [])

            if not bids or not asks:
                return {"bid": 0.5, "ask": 0.5, "mid": 0.5}

            bid_price = float(bids[0].get("price", 0.5))
            ask_price = float(asks[0].get("price", 0.5))
            mid_price = (bid_price + ask_price) / 2

            return {
                "bid": bid_price,
                "ask": ask_price,
                "mid": mid_price,
            }
        except Exception as e:
            log_error(f"Failed to calculate mid price: {e}")
            return {"bid": 0.5, "ask": 0.5, "mid": 0.5}

    def place_order(self, token_id: str, side: str, price: float, size: float) -> Dict[str, Any]:
        """
        Simplified placeholder for order placement.

        In DRY_RUN mode, bot_continuous.py will not call this.
        If DRY_RUN is turned off later, this method should be replaced
        with real signed Polymarket CLOB order placement logic.
        """
        log_info(
            f"place_order called token_id={token_id} side={side} price={price} size={size} "
            f"chain_id={self.chain_id}"
        )
        return {
            "status": "accepted_stub",
            "token_id": token_id,
            "side": side,
            "price": price,
            "size": size,
        }
