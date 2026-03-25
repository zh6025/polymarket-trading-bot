"""Polymarket CLOB API client."""

import requests
import time
import logging
from typing import Dict, List, Optional, Any

from lib.utils import APIClient, log_info, log_error, log_warn

logger = logging.getLogger(__name__)


class PolymarketClient:
    """
    Client for the Polymarket CLOB and Gamma APIs.

    Constructor accepts optional connection parameters so it can be called
    either with no arguments (legacy) or with explicit credentials:

        client = PolymarketClient()
        client = PolymarketClient(host, chain_id, private_key, proxy_address)
    """

    CLOB_BASE = "https://clob.polymarket.com"
    GAMMA_BASE = "https://gamma-api.polymarket.com"

    def __init__(
        self,
        host: str = "https://clob.polymarket.com",
        chain_id: int = 137,
        private_key: str = "",
        proxy_address: str = "",
    ):
        self.host = host or self.CLOB_BASE
        self.chain_id = chain_id
        self.private_key = private_key
        self.proxy_address = proxy_address
        self._http = APIClient(base_url=self.host)

    # ── Market discovery ─────────────────────────────────────────────────────

    def get_markets(self) -> List[Dict[str, Any]]:
        """Fetch market list from CLOB."""
        try:
            url = f"{self.CLOB_BASE}/markets"
            log_info("Fetching markets from CLOB")
            response = self._http.get(url)
            markets = response if isinstance(response, list) else response.get("data", [])
            log_info(f"Found {len(markets)} markets")
            return markets
        except Exception as e:
            log_error(f"Failed to fetch markets: {e}")
            return []

    def filter_btc_markets(self, markets: List[Dict]) -> List[Dict]:
        """Filter markets related to BTC up/down."""
        btc = [
            m for m in markets
            if m and (
                "BTC" in m.get("question", "").upper()
                or "BITCOIN" in m.get("question", "").upper()
            )
        ]
        log_info(f"Found {len(btc)} BTC markets")
        return btc

    def get_btc_5m_market_by_slug(self, slug: str) -> Optional[Dict]:
        """Fetch a BTC 5m event from the Gamma API by slug."""
        try:
            url = f"{self.GAMMA_BASE}/events/slug/{slug}"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data and isinstance(data, dict):
                    return data
            return None
        except Exception as e:
            log_error(f"Failed to fetch market by slug {slug!r}: {e}")
            return None

    def get_server_time(self) -> int:
        """Return Polymarket server UTC timestamp (falls back to local time)."""
        try:
            resp = requests.head(f"{self.CLOB_BASE}/", timeout=5)
            date_str = resp.headers.get("Date", "")
            if date_str:
                from email.utils import parsedate_to_datetime
                server_ts = int(parsedate_to_datetime(date_str).timestamp())
                diff = server_ts - int(time.time())
                if abs(diff) > 2:
                    log_warn(f"Local clock differs from server by {diff}s — using server time")
                return server_ts
        except Exception as e:
            log_warn(f"Could not read server time: {e}")
        return int(time.time())

    def get_current_btc_5m_market(self) -> Optional[Dict]:
        """
        Discover the currently active BTC 5-minute market.

        Tries the current 5-minute window and the next two windows.
        Returns the event dict if an active (acceptingOrders) market is found,
        otherwise None.
        """
        now = self.get_server_time()
        for offset in [0, 300, 600]:
            nearest = (now + offset) - ((now + offset) % 300)
            slug = f"btc-updown-5m-{nearest}"
            log_info(f"Trying market slug: {slug}")
            event = self.get_btc_5m_market_by_slug(slug)
            if not event:
                continue
            markets = event.get("markets", [])
            active = [
                m for m in markets
                if m.get("acceptingOrders", False) and not m.get("closed", True)
            ]
            if active:
                log_info(f"Active market found: {event.get('title', slug)}")
                return event
            log_warn(f"Market exists but has no active sub-markets, skipping: {slug}")

        log_error("No active BTC 5m market found")
        return None

    # ── Order book ───────────────────────────────────────────────────────────

    def get_orderbook(self, token_id: str) -> Dict[str, Any]:
        """Fetch the CLOB order book for *token_id*."""
        try:
            url = f"{self.CLOB_BASE}/book?token_id={token_id}"
            log_info(f"Fetching order book for token {token_id[:8]}…")
            return self._http.get(url)
        except Exception as e:
            log_error(f"Failed to fetch order book: {e}")
            raise

    # Alias for callers that use the snake_case variant
    def get_order_book(self, token_id: str) -> Dict[str, Any]:
        return self.get_orderbook(token_id)

    def calculate_mid_price(self, book: Dict[str, Any]) -> Dict[str, Optional[float]]:
        """Return {bid, ask, mid} from a raw CLOB order-book response."""
        try:
            bids = book.get("bids", [])
            asks = book.get("asks", [])

            # Bids are ascending (highest bid last); asks are descending (lowest ask last).
            best_bid = float(bids[-1]["price"]) if bids else None
            best_ask = float(asks[-1]["price"]) if asks else None

            if best_bid is not None and best_ask is not None:
                return {"bid": best_bid, "ask": best_ask, "mid": (best_bid + best_ask) / 2}
            if best_ask is not None:
                return {"bid": 0.0, "ask": best_ask, "mid": best_ask}
            if best_bid is not None:
                return {"bid": best_bid, "ask": 1.0, "mid": best_bid}

            return {"bid": None, "ask": None, "mid": None}
        except Exception as e:
            log_error(f"calculate_mid_price failed: {e}")
            return {"bid": None, "ask": None, "mid": None}

    # ── Order placement ──────────────────────────────────────────────────────

    def place_order(
        self,
        token_id: str,
        side: str,
        price: float,
        size: float,
    ) -> Optional[Dict[str, Any]]:
        """
        Place a limit order via the CLOB.

        In dry-run / demo mode (no private key) this logs the intended order
        and returns a simulated response instead of calling the API.
        """
        log_info(
            f"place_order: token={token_id[:8]}… side={side} price={price:.4f} size={size:.2f}"
        )

        if not self.private_key:
            log_warn("No PRIVATE_KEY configured — order not submitted (dry-run)")
            return {
                "status": "dry_run",
                "token_id": token_id,
                "side": side,
                "price": price,
                "size": size,
            }

        try:
            url = f"{self.CLOB_BASE}/order"
            payload = {
                "tokenID": token_id,
                "side": side.upper(),
                "price": str(price),
                "size": str(size),
                "orderType": "GTC",
            }
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            log_error(f"place_order failed: {e}")
            return None
