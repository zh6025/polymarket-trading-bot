"""
Bot state manager with crash recovery via atomic JSON persistence.
"""
import json
import os
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

STATE_FILE = os.environ.get("BOT_STATE_FILE", "bot_state.json")


@dataclass
class MarketPosition:
    """Single open/closed position for one market."""
    market_slug: str
    outcome: str          # 'YES' or 'NO'
    token_id: str
    entry_price: float
    size: float           # USDC notional
    entry_ts: str         # ISO timestamp
    exit_price: Optional[float] = None
    exit_ts: Optional[str] = None
    pnl: Optional[float] = None
    hedge_outcome: Optional[str] = None
    hedge_token_id: Optional[str] = None
    hedge_price: Optional[float] = None
    hedge_size: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "MarketPosition":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class BotState:
    """
    Global bot state with daily reset and crash-recovery persistence.

    Usage::

        state = BotState.load()
        state.trading_enabled = True
        state.save()
    """

    def __init__(self):
        self.trading_enabled: bool = False
        self.daily_pnl: float = 0.0
        self.consecutive_losses: int = 0
        self.daily_trade_count: int = 0
        self.open_positions: List[MarketPosition] = []
        self.closed_positions: List[MarketPosition] = []
        self._day_key: str = self._utc_day()

    # ------------------------------------------------------------------
    # Daily counter management
    # ------------------------------------------------------------------

    @staticmethod
    def _utc_day() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _maybe_reset_daily(self):
        """Reset daily counters when UTC day has changed."""
        today = self._utc_day()
        if today != self._day_key:
            logger.info(f"New UTC day ({today}), resetting daily counters.")
            self.daily_pnl = 0.0
            self.daily_trade_count = 0
            self._day_key = today

    def record_trade(self, pnl: float):
        """Call after each settled trade to update counters."""
        self._maybe_reset_daily()
        self.daily_pnl += pnl
        self.daily_trade_count += 1
        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

    # ------------------------------------------------------------------
    # Position tracking
    # ------------------------------------------------------------------

    def add_open_position(self, pos: MarketPosition):
        self._maybe_reset_daily()
        self.open_positions.append(pos)

    def close_position(self, market_slug: str, exit_price: float, pnl: float):
        self._maybe_reset_daily()
        for pos in self.open_positions:
            if pos.market_slug == market_slug:
                pos.exit_price = exit_price
                pos.exit_ts = datetime.now(timezone.utc).isoformat()
                pos.pnl = pnl
                self.closed_positions.append(pos)
                self.open_positions.remove(pos)
                self.record_trade(pnl)
                return
        logger.warning(f"close_position: no open position for {market_slug}")

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _to_dict(self) -> Dict[str, Any]:
        self._maybe_reset_daily()
        return {
            "trading_enabled": self.trading_enabled,
            "daily_pnl": self.daily_pnl,
            "consecutive_losses": self.consecutive_losses,
            "daily_trade_count": self.daily_trade_count,
            "day_key": self._day_key,
            "open_positions": [p.to_dict() for p in self.open_positions],
            "closed_positions": [p.to_dict() for p in self.closed_positions],
        }

    def save(self, path: str = STATE_FILE):
        """Atomic write: write temp file then rename."""
        tmp = path + ".tmp"
        try:
            with open(tmp, "w") as fh:
                json.dump(self._to_dict(), fh, indent=2)
            os.replace(tmp, path)
        except Exception as exc:
            logger.error(f"BotState.save failed: {exc}")

    @classmethod
    def load(cls, path: str = STATE_FILE) -> "BotState":
        """Load state from JSON file; returns fresh state if missing/corrupt."""
        state = cls()
        if not os.path.exists(path):
            return state
        try:
            with open(path) as fh:
                data = json.load(fh)
            state.trading_enabled = data.get("trading_enabled", False)
            state.daily_pnl = data.get("daily_pnl", 0.0)
            state.consecutive_losses = data.get("consecutive_losses", 0)
            state.daily_trade_count = data.get("daily_trade_count", 0)
            state._day_key = data.get("day_key", state._utc_day())
            state.open_positions = [
                MarketPosition.from_dict(p) for p in data.get("open_positions", [])
            ]
            state.closed_positions = [
                MarketPosition.from_dict(p) for p in data.get("closed_positions", [])
            ]
            state._maybe_reset_daily()
            logger.info(f"BotState loaded from {path}")
        except Exception as exc:
            logger.warning(f"BotState.load failed ({exc}), starting fresh.")
            state = cls()
        return state
