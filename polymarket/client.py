"""Polymarket CLOB client.

Wraps the py-clob-client library for market data and order operations.
All monetary values use USDC with $0..$1 price range for outcomes.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import requests

from polymarket.auth import get_api_credentials, get_chain_id, get_clob_host
from polymarket.endpoints import (
    CLOB_BALANCE,
    CLOB_BOOK,
    CLOB_FILLS,
    CLOB_ORDER,
    CLOB_ORDERS,
)
from polymarket.models import (
    Balance,
    Fill,
    Order,
    OrderBook,
    OrderStatus,
    Outcome,
    Side,
)

logger = logging.getLogger(__name__)

# py-clob-client is optional – fall back to raw HTTP if unavailable
try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import ApiCreds, OrderArgs, OrderType

    _HAS_PY_CLOB = True
except ImportError:  # pragma: no cover
    _HAS_PY_CLOB = False
    logger.warning("py-clob-client not installed; using raw HTTP fallback")


class PolymarketClient:
    """High-level client for the Polymarket CLOB API."""

    def __init__(self) -> None:
        self._creds = get_api_credentials()
        self._chain_id = get_chain_id()
        self._host = get_clob_host()
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})

        if _HAS_PY_CLOB:
            self._clob = ClobClient(
                host=self._host,
                chain_id=self._chain_id,
                key=self._creds["pk"],
                creds=ApiCreds(
                    api_key=self._creds["api_key"],
                    api_secret=self._creds["api_secret"],
                    api_passphrase=self._creds["api_passphrase"],
                )
                if self._creds["api_key"]
                else None,
            )
        else:
            self._clob = None

    # ------------------------------------------------------------------
    # Order book
    # ------------------------------------------------------------------

    def get_order_book(self, token_id: str) -> OrderBook:
        """Fetch the current order book for a token."""
        url = f"{self._host}{CLOB_BOOK}"
        resp = self._session.get(url, params={"token_id": token_id}, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        bids = [(float(b["price"]), float(b["size"])) for b in data.get("bids", [])]
        asks = [(float(a["price"]), float(a["size"])) for a in data.get("asks", [])]

        # Sort: bids descending, asks ascending
        bids.sort(key=lambda x: x[0], reverse=True)
        asks.sort(key=lambda x: x[0])

        return OrderBook(token_id=token_id, bids=bids, asks=asks)

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    def place_limit_order(
        self,
        market_id: str,
        token_id: str,
        outcome: Outcome,
        side: Side,
        price: float,
        size_usdc: float,
    ) -> Order:
        """Place a limit order.  Returns an Order with the server-assigned id."""
        if not _HAS_PY_CLOB or self._clob is None:
            raise RuntimeError("py-clob-client required for order placement")

        # Calculate token size from USDC notional
        token_size = round(size_usdc / price, 4)

        order_args = OrderArgs(
            token_id=token_id,
            price=price,
            size=token_size,
            side=side.value,
        )
        response = self._clob.create_and_post_order(order_args)
        order_id = response.get("orderID", response.get("id", "unknown"))

        return Order(
            order_id=order_id,
            market_id=market_id,
            token_id=token_id,
            outcome=outcome,
            side=side,
            price=price,
            size=size_usdc,
            status=OrderStatus.LIVE,
            created_at=time.time(),
        )

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order. Returns True if successful."""
        if not _HAS_PY_CLOB or self._clob is None:
            raise RuntimeError("py-clob-client required for order cancellation")
        try:
            self._clob.cancel(order_id)
            return True
        except Exception as exc:
            logger.warning("Failed to cancel order %s: %s", order_id, exc)
            return False

    def get_order(self, order_id: str) -> Optional[dict]:
        """Fetch a single order by ID."""
        url = f"{self._host}{CLOB_ORDERS}/{order_id}"
        try:
            resp = self._session.get(url, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.warning("Failed to fetch order %s: %s", order_id, exc)
            return None

    # ------------------------------------------------------------------
    # Fills
    # ------------------------------------------------------------------

    def get_fills(self, market_id: Optional[str] = None) -> list[Fill]:
        """Fetch recent fills, optionally filtered by market."""
        url = f"{self._host}{CLOB_FILLS}"
        params: dict = {}
        if market_id:
            params["market"] = market_id
        try:
            resp = self._session.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            fills = []
            for f in data.get("data", []):
                fills.append(
                    Fill(
                        fill_id=f.get("id", ""),
                        order_id=f.get("orderId", ""),
                        market_id=f.get("market", market_id or ""),
                        token_id=f.get("asset_id", ""),
                        outcome=Outcome.UP,  # resolved after by caller
                        side=Side(f.get("side", "BUY")),
                        price=float(f.get("price", 0)),
                        size=float(f.get("size", 0)),
                        timestamp=float(f.get("timestamp", time.time())),
                    )
                )
            return fills
        except Exception as exc:
            logger.warning("Failed to fetch fills: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Balance
    # ------------------------------------------------------------------

    def get_balance(self) -> Balance:
        """Fetch the current USDC balance/allowance."""
        url = f"{self._host}{CLOB_BALANCE}"
        params = {
            "asset_type": "USDC",
            "signature_type": 0,
        }
        try:
            resp = self._session.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            available = float(data.get("allowance", 0))
            locked = float(data.get("balance", 0)) - available
            return Balance(
                usdc_available=max(available, 0),
                usdc_locked=max(locked, 0),
            )
        except Exception as exc:
            logger.warning("Failed to fetch balance: %s", exc)
            return Balance(usdc_available=0.0, usdc_locked=0.0)
