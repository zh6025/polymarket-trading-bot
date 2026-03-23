import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Iterator, Optional


@dataclass
class PositionRecord:
    token_id: str
    side: str
    size: float
    entry_price: float
    created_at: str


class DataPersistence:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token_id TEXT NOT NULL,
                    side TEXT NOT NULL,
                    size REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token_id TEXT NOT NULL,
                    side TEXT NOT NULL,
                    size REAL NOT NULL,
                    price REAL NOT NULL,
                    realized_pnl REAL NOT NULL DEFAULT 0,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def add_position(self, token_id: str, side: str, size: float, entry_price: float) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO positions (token_id, side, size, entry_price, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (token_id, side, size, entry_price, datetime.utcnow().isoformat()),
            )

    def get_open_position(self, token_id: str) -> Optional[PositionRecord]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT token_id, side, size, entry_price, created_at
                FROM positions
                WHERE token_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (token_id,),
            ).fetchone()

        if not row:
            return None

        return PositionRecord(
            token_id=row[0],
            side=row[1],
            size=row[2],
            entry_price=row[3],
            created_at=row[4],
        )

    def close_positions(self, token_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM positions WHERE token_id = ?", (token_id,))

    def record_trade(
        self,
        token_id: str,
        side: str,
        size: float,
        price: float,
        realized_pnl: float,
        reason: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO trades (token_id, side, size, price, realized_pnl, reason, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    token_id,
                    side,
                    size,
                    price,
                    realized_pnl,
                    reason,
                    datetime.utcnow().isoformat(),
                ),
            )
