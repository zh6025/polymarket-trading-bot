"""Bot state management: load, save, and update persistent trading state."""

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class BotState:
    trading_enabled: bool = True
    daily_realized_pnl_usdc: float = 0.0
    trade_count: int = 0
    consecutive_losses: int = 0
    open_positions: Dict[str, Any] = field(default_factory=dict)
    last_reset_date: str = ""
    last_trade_ts: int = 0

    def market_has_position(self, market_id: str) -> bool:
        return market_id in self.open_positions


def load_state(file_path: str, trading_enabled: bool = True) -> BotState:
    """Load bot state from JSON file, or return a fresh state."""
    path = Path(file_path)
    if path.exists():
        try:
            with path.open("r") as f:
                data = json.load(f)
            state = BotState(
                trading_enabled=data.get("trading_enabled", trading_enabled),
                daily_realized_pnl_usdc=float(data.get("daily_realized_pnl_usdc", 0.0)),
                trade_count=int(data.get("trade_count", 0)),
                consecutive_losses=int(data.get("consecutive_losses", 0)),
                open_positions=data.get("open_positions", {}),
                last_reset_date=data.get("last_reset_date", ""),
                last_trade_ts=int(data.get("last_trade_ts", 0)),
            )
            logger.info(f"State loaded from {file_path}")
            return state
        except Exception as e:
            logger.warning(f"Failed to load state from {file_path}: {e} — using fresh state")

    return BotState(trading_enabled=trading_enabled)


def save_state(state: BotState, file_path: str) -> None:
    """Persist bot state to a JSON file."""
    try:
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w") as f:
            json.dump(asdict(state), f, indent=2)
        logger.debug(f"State saved to {file_path}")
    except Exception as e:
        logger.error(f"Failed to save state to {file_path}: {e}")


def reset_daily_if_needed(state: BotState, now_ts: int) -> None:
    """Reset daily counters when the calendar date has changed."""
    today = datetime.fromtimestamp(now_ts, tz=timezone.utc).date().isoformat()
    if state.last_reset_date != today:
        logger.info(f"New day detected ({today}), resetting daily counters")
        state.daily_realized_pnl_usdc = 0.0
        state.trade_count = 0
        state.last_reset_date = today


def record_trade_open(
    state: BotState,
    market_id: str,
    now_ts: int,
    main_outcome: str,
    main_token_id: str,
    main_price: float,
    main_size: float,
    hedge_outcome: str,
    hedge_token_id: str,
    hedge_price: float,
    hedge_size: float,
) -> None:
    """Record an open trade pair (main + hedge) in state."""
    state.open_positions[market_id] = {
        "opened_at": now_ts,
        "main": {
            "outcome": main_outcome,
            "token_id": main_token_id,
            "price": main_price,
            "size": main_size,
        },
        "hedge": {
            "outcome": hedge_outcome,
            "token_id": hedge_token_id,
            "price": hedge_price,
            "size": hedge_size,
        },
    }
    state.trade_count += 1
    state.last_trade_ts = now_ts
    logger.info(
        f"Trade opened: market={market_id} main={main_outcome}@{main_price:.4f}x{main_size} "
        f"hedge={hedge_outcome}@{hedge_price:.4f}x{hedge_size}"
    )
