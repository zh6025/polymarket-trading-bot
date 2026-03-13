"""SQLite persistence layer.

Schema
------
  orders      – all orders placed (including status updates)
  fills       – all trade fills
  pnl_daily   – daily PnL snapshots
  config_snapshots – timestamped copy of configuration at startup
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path("/data/trading_bot.db")


class Database:
    """Thread-safe SQLite wrapper."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._path = db_path or DEFAULT_DB_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._create_tables()
        logger.info("Database opened at %s", self._path)

    # ------------------------------------------------------------------
    # Schema creation
    # ------------------------------------------------------------------

    def _create_tables(self) -> None:
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    order_id        TEXT PRIMARY KEY,
                    market_id       TEXT NOT NULL,
                    token_id        TEXT NOT NULL,
                    outcome         TEXT NOT NULL,
                    side            TEXT NOT NULL,
                    price           REAL NOT NULL,
                    size_usdc       REAL NOT NULL,
                    status          TEXT NOT NULL,
                    filled_size     REAL DEFAULT 0,
                    avg_fill_price  REAL DEFAULT 0,
                    created_at      REAL NOT NULL,
                    updated_at      REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS fills (
                    fill_id         TEXT PRIMARY KEY,
                    order_id        TEXT NOT NULL,
                    market_id       TEXT NOT NULL,
                    token_id        TEXT NOT NULL,
                    outcome         TEXT NOT NULL,
                    side            TEXT NOT NULL,
                    price           REAL NOT NULL,
                    size_usdc       REAL NOT NULL,
                    timestamp       REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS pnl_daily (
                    date_utc        TEXT NOT NULL,
                    realised_usdc   REAL NOT NULL,
                    recorded_at     REAL NOT NULL,
                    PRIMARY KEY (date_utc)
                );

                CREATE TABLE IF NOT EXISTS config_snapshots (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    config_json     TEXT NOT NULL,
                    recorded_at     REAL NOT NULL
                );
                """
            )

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    def upsert_order(self, order) -> None:
        """Insert or update an order record."""
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO orders
                    (order_id, market_id, token_id, outcome, side, price,
                     size_usdc, status, filled_size, avg_fill_price, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(order_id) DO UPDATE SET
                    status=excluded.status,
                    filled_size=excluded.filled_size,
                    avg_fill_price=excluded.avg_fill_price,
                    updated_at=excluded.updated_at
                """,
                (
                    order.order_id,
                    order.market_id,
                    order.token_id,
                    order.outcome.value,
                    order.side.value,
                    order.price,
                    order.size,
                    order.status.value,
                    order.filled_size,
                    order.avg_fill_price,
                    order.created_at,
                    time.time(),
                ),
            )

    # ------------------------------------------------------------------
    # Fills
    # ------------------------------------------------------------------

    def insert_fill(self, fill) -> None:
        """Insert a fill record (ignores duplicates)."""
        with self._conn:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO fills
                    (fill_id, order_id, market_id, token_id, outcome, side,
                     price, size_usdc, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fill.fill_id,
                    fill.order_id,
                    fill.market_id,
                    fill.token_id,
                    fill.outcome.value,
                    fill.side.value,
                    fill.price,
                    fill.size,
                    fill.timestamp,
                ),
            )

    # ------------------------------------------------------------------
    # Daily PnL
    # ------------------------------------------------------------------

    def upsert_daily_pnl(self, date_utc: str, realised_usdc: float) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO pnl_daily (date_utc, realised_usdc, recorded_at)
                VALUES (?, ?, ?)
                ON CONFLICT(date_utc) DO UPDATE SET
                    realised_usdc=excluded.realised_usdc,
                    recorded_at=excluded.recorded_at
                """,
                (date_utc, realised_usdc, time.time()),
            )

    def get_daily_pnl(self, date_utc: str) -> Optional[float]:
        row = self._conn.execute(
            "SELECT realised_usdc FROM pnl_daily WHERE date_utc = ?", (date_utc,)
        ).fetchone()
        return float(row["realised_usdc"]) if row else None

    # ------------------------------------------------------------------
    # Config snapshots
    # ------------------------------------------------------------------

    def save_config(self, config: dict) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO config_snapshots (config_json, recorded_at) VALUES (?, ?)",
                (json.dumps(config), time.time()),
            )

    # ------------------------------------------------------------------
    # Teardown
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._conn.close()
        logger.info("Database closed")
