"""Binance BTC/USDT price feed.

Uses the Binance public WebSocket stream for real-time trade data and falls
back to REST polling when the WebSocket is unavailable.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Optional

import requests

from feeds.base import PriceFeed
from polymarket.endpoints import (
    BINANCE_KLINES,
    BINANCE_PRICE,
    BINANCE_REST_BASE,
    BINANCE_WS_BASE,
)

logger = logging.getLogger(__name__)

SYMBOL = "BTCUSDT"
TRADE_STREAM = f"{BINANCE_WS_BASE}/{SYMBOL.lower()}@trade"

# How often (seconds) to fall back to REST polling if WS fails
REST_POLL_INTERVAL = 5


class BinanceFeed(PriceFeed):
    """Real-time BTC/USDT price feed backed by Binance."""

    def __init__(self) -> None:
        super().__init__()
        self._ws_thread: Optional[threading.Thread] = None
        self._poll_thread: Optional[threading.Thread] = None
        self._running = False
        self._ws_ok = False
        self._session = requests.Session()

    # ------------------------------------------------------------------
    # Start / stop
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._bootstrap_history()
        self._ws_thread = threading.Thread(
            target=self._run_websocket, daemon=True, name="binance-ws"
        )
        self._ws_thread.start()
        # Also start REST fallback thread
        self._poll_thread = threading.Thread(
            target=self._run_rest_poll, daemon=True, name="binance-rest"
        )
        self._poll_thread.start()
        logger.info("Binance feed started")

    def stop(self) -> None:
        self._running = False
        logger.info("Binance feed stopped")

    # ------------------------------------------------------------------
    # REST bootstrap – pre-fill history with recent klines
    # ------------------------------------------------------------------

    def _bootstrap_history(self) -> None:
        """Pre-load ~30 minutes of 1-minute closes to prime the history."""
        try:
            resp = self._session.get(
                f"{BINANCE_REST_BASE}{BINANCE_KLINES}",
                params={"symbol": SYMBOL, "interval": "1m", "limit": 30},
                timeout=10,
            )
            resp.raise_for_status()
            klines = resp.json()
            for k in klines:
                # kline: [open_time, open, high, low, close, volume, close_time, ...]
                close_time = float(k[6]) / 1000
                close_price = float(k[4])
                self._record(close_price, close_time)
            logger.debug("Bootstrapped %d price points from Binance klines", len(klines))
        except Exception as exc:
            logger.warning("Binance history bootstrap failed: %s", exc)

    # ------------------------------------------------------------------
    # WebSocket feed
    # ------------------------------------------------------------------

    def _run_websocket(self) -> None:
        """Connect to Binance trade stream; reconnect on error."""
        while self._running:
            try:
                import websocket  # type: ignore

                ws = websocket.WebSocketApp(
                    TRADE_STREAM,
                    on_message=self._on_ws_message,
                    on_error=self._on_ws_error,
                    on_close=self._on_ws_close,
                    on_open=self._on_ws_open,
                )
                ws.run_forever(ping_interval=20, ping_timeout=10)
            except Exception as exc:
                logger.warning("Binance WS error: %s – reconnecting in 5s", exc)
            if self._running:
                time.sleep(5)

    def _on_ws_open(self, ws) -> None:
        self._ws_ok = True
        logger.debug("Binance WebSocket connected")

    def _on_ws_close(self, ws, code, msg) -> None:
        self._ws_ok = False
        logger.debug("Binance WebSocket closed: %s %s", code, msg)

    def _on_ws_error(self, ws, error) -> None:
        self._ws_ok = False
        logger.warning("Binance WebSocket error: %s", error)

    def _on_ws_message(self, ws, raw: str) -> None:
        try:
            msg = json.loads(raw)
            if msg.get("e") == "trade":
                price = float(msg["p"])
                ts = float(msg["T"]) / 1000
                self._record(price, ts)
        except Exception as exc:
            logger.debug("WS message parse error: %s", exc)

    # ------------------------------------------------------------------
    # REST fallback polling
    # ------------------------------------------------------------------

    def _run_rest_poll(self) -> None:
        """Periodically fetch price via REST when WebSocket is not working."""
        while self._running:
            time.sleep(REST_POLL_INTERVAL)
            if self._ws_ok:
                continue  # WS is working, no need to poll
            try:
                resp = self._session.get(
                    f"{BINANCE_REST_BASE}{BINANCE_PRICE}",
                    params={"symbol": SYMBOL},
                    timeout=5,
                )
                resp.raise_for_status()
                data = resp.json()
                price = float(data["price"])
                self._record(price)
            except Exception as exc:
                logger.warning("Binance REST poll failed: %s", exc)

    # ------------------------------------------------------------------
    # OHLCV helpers for trend calculation
    # ------------------------------------------------------------------

    def get_klines(self, interval: str, limit: int) -> list[dict]:
        """Return recent OHLCV klines from Binance REST.

        Args:
            interval: Binance interval string e.g. "5m", "15m"
            limit: number of candles

        Returns:
            List of dicts with keys: open_time, open, high, low, close, volume
        """
        resp = self._session.get(
            f"{BINANCE_REST_BASE}{BINANCE_KLINES}",
            params={"symbol": SYMBOL, "interval": interval, "limit": limit},
            timeout=10,
        )
        resp.raise_for_status()
        klines = resp.json()
        return [
            {
                "open_time": float(k[0]) / 1000,
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
                "close_time": float(k[6]) / 1000,
            }
            for k in klines
        ]
