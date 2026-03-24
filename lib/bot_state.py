import json
import os
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any


@dataclass
class MarketPosition:
    market_id: str
    opened_at_ts: int
    main_outcome: str
    main_token_id: str
    main_price: float
    main_size: float
    hedge_outcome: Optional[str] = None
    hedge_token_id: Optional[str] = None
    hedge_price: float = 0.0
    hedge_size: float = 0.0
    status: str = "OPEN"
    closed_at_ts: Optional[int] = None
    realized_pnl: float = 0.0


@dataclass
class BotState:
    current_day: str
    daily_realized_pnl_usdc: float = 0.0
    consecutive_losses: int = 0
    daily_trade_count: int = 0
    open_positions: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    closed_positions: List[Dict[str, Any]] = field(default_factory=list)
    trading_enabled: bool = False

    def market_has_position(self, market_id: str) -> bool:
        pos = self.open_positions.get(market_id)
        return pos is not None and pos.get("status") == "OPEN"


def utc_day_string(ts: Optional[int] = None) -> str:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%d")


def reset_daily_if_needed(state: BotState, now_ts: Optional[int] = None) -> None:
    today = utc_day_string(now_ts)
    if state.current_day != today:
        state.current_day = today
        state.daily_realized_pnl_usdc = 0.0
        state.consecutive_losses = 0
        state.daily_trade_count = 0


def save_state(state: BotState, file_path: str) -> None:
    data = asdict(state)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_state(file_path: str, trading_enabled: bool = False) -> BotState:
    if not os.path.exists(file_path):
        return BotState(
            current_day=utc_day_string(),
            trading_enabled=trading_enabled,
        )

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return BotState(
        current_day=data.get("current_day", utc_day_string()),
        daily_realized_pnl_usdc=data.get("daily_realized_pnl_usdc", 0.0),
        consecutive_losses=data.get("consecutive_losses", 0),
        daily_trade_count=data.get("daily_trade_count", 0),
        open_positions=data.get("open_positions", {}),
        closed_positions=data.get("closed_positions", []),
        trading_enabled=trading_enabled,
    )


def record_trade_open(
    state: BotState,
    market_id: str,
    now_ts: int,
    main_outcome: str,
    main_token_id: str,
    main_price: float,
    main_size: float,
    hedge_outcome: Optional[str] = None,
    hedge_token_id: Optional[str] = None,
    hedge_price: float = 0.0,
    hedge_size: float = 0.0,
) -> None:
    pos = MarketPosition(
        market_id=market_id,
        opened_at_ts=now_ts,
        main_outcome=main_outcome,
        main_token_id=main_token_id,
        main_price=main_price,
        main_size=main_size,
        hedge_outcome=hedge_outcome,
        hedge_token_id=hedge_token_id,
        hedge_price=hedge_price,
        hedge_size=hedge_size,
        status="OPEN",
    )
    state.open_positions[market_id] = asdict(pos)
    state.daily_trade_count += 1


def record_trade_close(
    state: BotState,
    market_id: str,
    now_ts: int,
    realized_pnl: float,
) -> None:
    pos = state.open_positions.get(market_id)
    if not pos:
        return

    pos["status"] = "CLOSED"
    pos["closed_at_ts"] = now_ts
    pos["realized_pnl"] = round(realized_pnl, 4)

    state.daily_realized_pnl_usdc = round(state.daily_realized_pnl_usdc + realized_pnl, 4)

    if realized_pnl < 0:
        state.consecutive_losses += 1
    else:
        state.consecutive_losses = 0

    state.closed_positions.append(pos)
    del state.open_positions[market_id]
