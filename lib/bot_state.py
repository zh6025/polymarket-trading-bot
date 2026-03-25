"""
Bot state persistence and daily risk tracking.

Supports JSON-based crash recovery, daily PnL reset,
consecutive loss tracking, and open position management.
"""

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, date
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class MarketPosition:
    """Represents a single open position."""
    token_id: str
    outcome: str          # e.g. "YES" or "NO"
    side: str             # "buy" or "sell"
    price: float
    size: float
    timestamp: str = ""
    market_question: str = ""

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "MarketPosition":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class BotState:
    """Global bot state with daily risk counters and open positions."""
    daily_pnl: float = 0.0
    total_pnl: float = 0.0
    consecutive_losses: int = 0
    daily_trade_count: int = 0
    daily_win_count: int = 0
    last_reset_date: str = ""          # ISO date string "YYYY-MM-DD"
    open_positions: List[dict] = field(default_factory=list)
    is_halted: bool = False
    halt_reason: str = ""

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "BotState":
        obj = cls()
        obj.daily_pnl = float(d.get("daily_pnl", 0.0))
        obj.total_pnl = float(d.get("total_pnl", 0.0))
        obj.consecutive_losses = int(d.get("consecutive_losses", 0))
        obj.daily_trade_count = int(d.get("daily_trade_count", 0))
        obj.daily_win_count = int(d.get("daily_win_count", 0))
        obj.last_reset_date = str(d.get("last_reset_date", ""))
        obj.open_positions = list(d.get("open_positions", []))
        obj.is_halted = bool(d.get("is_halted", False))
        obj.halt_reason = str(d.get("halt_reason", ""))
        return obj


def load_state(path: str) -> BotState:
    """Load BotState from JSON file; returns a fresh state if file is missing or corrupt."""
    if not os.path.exists(path):
        logger.info(f"No state file at {path}, starting fresh.")
        return BotState()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        state = BotState.from_dict(data)
        logger.info(f"State loaded from {path}: daily_pnl={state.daily_pnl:.2f}, trades={state.daily_trade_count}")
        return state
    except Exception as e:
        logger.error(f"Failed to load state from {path}: {e}. Starting fresh.")
        return BotState()


def save_state(state: BotState, path: str) -> None:
    """Persist BotState to JSON file atomically."""
    try:
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(state.to_dict(), f, indent=2)
        os.replace(tmp_path, path)
        logger.debug(f"State saved to {path}")
    except Exception as e:
        logger.error(f"Failed to save state to {path}: {e}")


def reset_daily_if_needed(state: BotState) -> BotState:
    """Reset daily counters if the calendar date has rolled over."""
    today = date.today().isoformat()
    if state.last_reset_date != today:
        logger.info(f"New day detected ({today}). Resetting daily counters.")
        state.daily_pnl = 0.0
        state.daily_trade_count = 0
        state.daily_win_count = 0
        state.consecutive_losses = 0
        state.last_reset_date = today
        state.is_halted = False
        state.halt_reason = ""
    return state


def record_trade_open(state: BotState, position: MarketPosition) -> BotState:
    """Record an opened trade in state and increment daily trade counter."""
    state.open_positions.append(position.to_dict())
    state.daily_trade_count += 1
    logger.info(
        f"Trade recorded: {position.outcome} {position.side} size={position.size:.2f} "
        f"price={position.price:.4f}. Daily trades: {state.daily_trade_count}"
    )
    return state


def record_trade_close(state: BotState, token_id: str, pnl: float) -> BotState:
    """Record a closed trade, update PnL and consecutive loss counter."""
    # Remove matching open position
    state.open_positions = [p for p in state.open_positions if p.get("token_id") != token_id]

    state.daily_pnl += pnl
    state.total_pnl += pnl

    if pnl < 0:
        state.consecutive_losses += 1
    else:
        state.consecutive_losses = 0
        state.daily_win_count += 1

    logger.info(
        f"Trade closed: pnl={pnl:+.4f}, daily_pnl={state.daily_pnl:+.4f}, "
        f"consecutive_losses={state.consecutive_losses}"
    )
    return state


def halt_bot(state: BotState, reason: str) -> BotState:
    """Mark bot as halted with a reason."""
    state.is_halted = True
    state.halt_reason = reason
    logger.warning(f"Bot halted: {reason}")
    return state
