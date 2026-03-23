"""
BotState and MarketPosition – persistent state manager for the trading bot.

Tracks per-session and per-market state, persists to JSON for crash recovery,
and enforces daily counter resets on UTC day change.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_DEFAULT_STATE_PATH = "bot_state.json"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class MarketPosition:
    """Tracks a single open or closed position in a market."""
    market_id: str
    main_side: str              # "UP" or "DOWN"
    main_entry_price: float
    main_size: float
    hedge_side: Optional[str] = None
    hedge_entry_price: Optional[float] = None
    hedge_size: Optional[float] = None
    opened_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    closed_at: Optional[str] = None
    gross_pnl: Optional[float] = None
    net_pnl: Optional[float] = None
    winner: Optional[str] = None   # "main", "hedge", or None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "MarketPosition":
        return cls(**d)


@dataclass
class BotState:
    """
    Top-level state object persisted across restarts.

    Attributes
    ----------
    trading_enabled : bool
        Master kill-switch; if False the bot will not place any real orders.
    current_day : str
        ISO date string (UTC) of the current trading day.
    daily_pnl : float
        Realised PnL for *current_day* (USDC).
    consecutive_losses : int
        Number of consecutive losing trades since last win.
    daily_trade_count : int
        Number of trade opens on *current_day*.
    open_positions : dict
        Keyed by market_id → MarketPosition (currently open).
    closed_positions : list
        History of closed MarketPosition objects.
    """

    trading_enabled: bool = False
    current_day: str = field(default_factory=lambda: date.today().isoformat())
    daily_pnl: float = 0.0
    consecutive_losses: int = 0
    daily_trade_count: int = 0
    open_positions: Dict[str, MarketPosition] = field(default_factory=dict)
    closed_positions: List[MarketPosition] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Day management
    # ------------------------------------------------------------------

    def _today_utc(self) -> str:
        return datetime.utcnow().date().isoformat()

    def reset_daily_counters_if_new_day(self) -> bool:
        """
        Reset daily counters if the UTC date has changed.

        Returns True if a reset occurred.
        """
        today = self._today_utc()
        if today != self.current_day:
            logger.info(
                "New UTC trading day detected (%s → %s). Resetting daily counters.",
                self.current_day,
                today,
            )
            self.current_day = today
            self.daily_pnl = 0.0
            self.daily_trade_count = 0
            self.consecutive_losses = 0
            return True
        return False

    # ------------------------------------------------------------------
    # Position management
    # ------------------------------------------------------------------

    def has_open_position(self, market_id: str) -> bool:
        """Return True if there is already an open position for *market_id*."""
        return market_id in self.open_positions

    def record_trade_open(self, position: MarketPosition) -> None:
        """
        Record a newly opened position.

        Raises ValueError if a position for this market is already tracked.
        """
        self.reset_daily_counters_if_new_day()
        if self.has_open_position(position.market_id):
            raise ValueError(
                f"Position already open for market {position.market_id!r}. "
                "Duplicate entries are not allowed."
            )
        self.open_positions[position.market_id] = position
        self.daily_trade_count += 1
        logger.info(
            "Position opened: market=%s main_side=%s main_price=%.4f main_size=%.2f",
            position.market_id,
            position.main_side,
            position.main_entry_price,
            position.main_size,
        )

    def record_trade_close(
        self,
        market_id: str,
        *,
        gross_pnl: float,
        net_pnl: float,
        winner: Optional[str] = None,
        fees: float = 0.0,
    ) -> MarketPosition:
        """
        Mark an open position as closed, update PnL and consecutive losses.

        Returns the closed MarketPosition.
        Raises KeyError if no open position exists for *market_id*.
        """
        self.reset_daily_counters_if_new_day()
        if market_id not in self.open_positions:
            raise KeyError(f"No open position found for market {market_id!r}.")

        pos = self.open_positions.pop(market_id)
        pos.closed_at = datetime.utcnow().isoformat()
        pos.gross_pnl = gross_pnl
        pos.net_pnl = net_pnl
        pos.winner = winner

        self.daily_pnl += net_pnl
        self.closed_positions.append(pos)

        if net_pnl >= 0:
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1

        logger.info(
            "Position closed: market=%s net_pnl=%.4f gross_pnl=%.4f fees=%.4f "
            "daily_pnl=%.4f consecutive_losses=%d",
            market_id,
            net_pnl,
            gross_pnl,
            fees,
            self.daily_pnl,
            self.consecutive_losses,
        )
        return pos

    # ------------------------------------------------------------------
    # Serialisation / deserialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "trading_enabled": self.trading_enabled,
            "current_day": self.current_day,
            "daily_pnl": self.daily_pnl,
            "consecutive_losses": self.consecutive_losses,
            "daily_trade_count": self.daily_trade_count,
            "open_positions": {
                k: v.to_dict() for k, v in self.open_positions.items()
            },
            "closed_positions": [p.to_dict() for p in self.closed_positions],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "BotState":
        open_pos: Dict[str, MarketPosition] = {
            k: MarketPosition.from_dict(v)
            for k, v in d.get("open_positions", {}).items()
        }
        closed_pos: List[MarketPosition] = [
            MarketPosition.from_dict(p)
            for p in d.get("closed_positions", [])
        ]
        return cls(
            trading_enabled=bool(d.get("trading_enabled", False)),
            current_day=d.get("current_day", date.today().isoformat()),
            daily_pnl=float(d.get("daily_pnl", 0.0)),
            consecutive_losses=int(d.get("consecutive_losses", 0)),
            daily_trade_count=int(d.get("daily_trade_count", 0)),
            open_positions=open_pos,
            closed_positions=closed_pos,
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: str = _DEFAULT_STATE_PATH) -> None:
        """Persist the current state to a JSON file (atomic write)."""
        tmp_path = path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(self.to_dict(), fh, indent=2, ensure_ascii=False)
            os.replace(tmp_path, path)
            logger.debug("Bot state saved to %s", path)
        except Exception as exc:
            logger.error("Failed to save bot state to %s: %s", path, exc)
            raise

    @classmethod
    def load(cls, path: str = _DEFAULT_STATE_PATH) -> "BotState":
        """
        Load state from a JSON file.

        Returns a fresh BotState if the file does not exist or is corrupt.
        """
        if not os.path.exists(path):
            logger.info("No state file at %s – starting with fresh state.", path)
            return cls()
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            state = cls.from_dict(data)
            logger.info(
                "Bot state loaded from %s (day=%s daily_pnl=%.2f open=%d)",
                path,
                state.current_day,
                state.daily_pnl,
                len(state.open_positions),
            )
            return state
        except Exception as exc:
            logger.error(
                "Failed to load bot state from %s: %s. Starting fresh.",
                path,
                exc,
            )
            return cls()

    # ------------------------------------------------------------------
    # Summary helpers
    # ------------------------------------------------------------------

    def summary(self) -> dict:
        """Return a lightweight dict suitable for logging each cycle."""
        return {
            "trading_enabled": self.trading_enabled,
            "current_day": self.current_day,
            "daily_pnl": round(self.daily_pnl, 4),
            "daily_trade_count": self.daily_trade_count,
            "consecutive_losses": self.consecutive_losses,
            "open_positions": list(self.open_positions.keys()),
            "total_closed": len(self.closed_positions),
        }
