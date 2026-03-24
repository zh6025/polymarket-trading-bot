from dataclasses import dataclass
from datetime import datetime, date
from typing import Optional


@dataclass
class RiskDecision:
    allowed: bool
    reason: str = ""


class RiskManager:
    def __init__(
        self,
        max_position_size: float,
        max_daily_loss: float,
        max_trades_per_day: int,
        cooldown_seconds: int,
    ):
        self.max_position_size = max_position_size
        self.max_daily_loss = max_daily_loss
        self.max_trades_per_day = max_trades_per_day
        self.cooldown_seconds = cooldown_seconds

        self.current_day: date = datetime.utcnow().date()
        self.daily_realized_pnl: float = 0.0
        self.daily_trade_count: int = 0
        self.last_trade_time: Optional[datetime] = None

    def _roll_day_if_needed(self) -> None:
        today = datetime.utcnow().date()
        if today != self.current_day:
            self.current_day = today
            self.daily_realized_pnl = 0.0
            self.daily_trade_count = 0
            self.last_trade_time = None

    def record_trade(self, realized_pnl: float = 0.0) -> None:
        self._roll_day_if_needed()
        self.daily_trade_count += 1
        self.daily_realized_pnl += realized_pnl
        self.last_trade_time = datetime.utcnow()

    def can_open_position(self, current_position_size: float, new_order_size: float) -> RiskDecision:
        self._roll_day_if_needed()

        if self.daily_realized_pnl <= -abs(self.max_daily_loss):
            return RiskDecision(False, "max_daily_loss_reached")

        if self.daily_trade_count >= self.max_trades_per_day:
            return RiskDecision(False, "max_trades_per_day_reached")

        if (current_position_size + new_order_size) > self.max_position_size:
            return RiskDecision(False, "max_position_size_exceeded")

        if self.last_trade_time is not None:
            elapsed = (datetime.utcnow() - self.last_trade_time).total_seconds()
            if elapsed < self.cooldown_seconds:
                return RiskDecision(False, "cooldown_active")

        return RiskDecision(True, "ok")
