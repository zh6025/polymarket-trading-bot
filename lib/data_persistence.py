"""SQLite-backed persistence for trades and open positions."""

import sqlite3
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


@dataclass
class Position:
    token_id: str
    side: str
    entry_price: float
    size: float
    opened_at: str


class DataPersistence:
    """Handle data persistence with SQLite."""

    def __init__(self, db_path: str = "bot_data.db"):
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None
        self._initialize_db()

    # ── Schema ────────────────────────────────────────────────────────────────

    def _initialize_db(self) -> None:
        self.conn = sqlite3.connect(self.db_path)
        cursor = self.conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY,
                order_id TEXT UNIQUE,
                token_id TEXT,
                side TEXT,
                price REAL,
                size REAL,
                realized_pnl REAL DEFAULT 0,
                timestamp TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY,
                token_id TEXT UNIQUE,
                side TEXT,
                entry_price REAL,
                size REAL,
                opened_at TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS prices (
                id INTEGER PRIMARY KEY,
                token_id TEXT,
                price REAL,
                bid REAL,
                ask REAL,
                timestamp TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS performance (
                id INTEGER PRIMARY KEY,
                timestamp TEXT,
                total_pnl REAL,
                unrealized_pnl REAL,
                positions TEXT,
                statistics TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        self.conn.commit()
        logger.info("Database initialized")

    # ── Positions ─────────────────────────────────────────────────────────────

    def get_open_position(self, token_id: str) -> Optional[Position]:
        """Return the open position for *token_id*, or None."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT token_id, side, entry_price, size, opened_at "
                "FROM positions WHERE token_id = ?",
                (token_id,),
            )
            row = cursor.fetchone()
            if row:
                return Position(
                    token_id=row[0],
                    side=row[1],
                    entry_price=row[2],
                    size=row[3],
                    opened_at=row[4],
                )
            return None
        except Exception as e:
            logger.error(f"get_open_position failed: {e}")
            return None

    def add_position(
        self,
        token_id: str,
        side: str,
        entry_price: float,
        size: float,
    ) -> bool:
        """Insert or replace an open position record."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO positions (token_id, side, entry_price, size, opened_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (token_id, side, entry_price, size, datetime.now().isoformat()),
            )
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"add_position failed: {e}")
            return False

    def close_positions(self, token_id: str) -> bool:
        """Remove the open position for *token_id*."""
        try:
            cursor = self.conn.cursor()
            cursor.execute("DELETE FROM positions WHERE token_id = ?", (token_id,))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"close_positions failed: {e}")
            return False

    # ── Trades ────────────────────────────────────────────────────────────────

    def record_trade(
        self,
        token_id: str,
        side: str,
        price: float,
        size: float,
        realized_pnl: float = 0.0,
        order_id: Optional[str] = None,
        timestamp: Optional[str] = None,
    ) -> bool:
        """Persist a completed trade."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                INSERT INTO trades (order_id, token_id, side, price, size, realized_pnl, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order_id or f"trade_{datetime.now().timestamp()}",
                    token_id,
                    side,
                    price,
                    size,
                    realized_pnl,
                    timestamp or datetime.now().isoformat(),
                ),
            )
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"record_trade failed: {e}")
            return False

    def save_trade(self, trade: Dict[str, Any]) -> bool:
        """Legacy helper — delegates to record_trade."""
        return self.record_trade(
            token_id=trade.get("token_id", ""),
            side=trade.get("side", ""),
            price=float(trade.get("price", 0)),
            size=float(trade.get("size", 0)),
            order_id=trade.get("order_id"),
            timestamp=trade.get("timestamp"),
        )

    def get_trades(self, hours: int = 24) -> List[Dict]:
        """Return trades from the last *hours* hours."""
        try:
            cursor = self.conn.cursor()
            cutoff = datetime.now() - timedelta(hours=hours)
            cursor.execute(
                "SELECT * FROM trades WHERE created_at > ? ORDER BY created_at DESC",
                (cutoff,),
            )
            cols = [d[0] for d in cursor.description]
            return [dict(zip(cols, row)) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"get_trades failed: {e}")
            return []

    def get_performance_summary(self, hours: int = 24) -> Dict[str, Any]:
        """Return basic PnL summary for the last *hours* hours."""
        trades = self.get_trades(hours=hours)
        total_pnl = sum(t.get("realized_pnl", 0) for t in trades)
        return {"total_trades": len(trades), "total_pnl": total_pnl, "avg_pnl": total_pnl / len(trades) if trades else 0}

    def save_price(
        self,
        token_id: str,
        price: float,
        bid: float,
        ask: float,
        timestamp: str,
    ) -> bool:
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "INSERT INTO prices (token_id, price, bid, ask, timestamp) VALUES (?, ?, ?, ?, ?)",
                (token_id, price, bid, ask, timestamp),
            )
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"save_price failed: {e}")
            return False

    def close(self) -> None:
        """Close the database connection."""
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed")
