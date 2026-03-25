"""Risk manager for the continuous polling bot."""

import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class RiskCheckResult:
    allowed: bool
    reason: str


class RiskManager:
    """
    Risk manager used by bot_continuous.py.

    Constructor keyword arguments map directly to environment config values.
    """

    def __init__(
        self,
        max_position_size: float = 500.0,
        max_daily_loss: float = 100.0,
        max_trades_per_day: int = 50,
        cooldown_seconds: int = 30,
    ):
        self.max_position_size = max_position_size
        self.max_daily_loss = max_daily_loss
        self.max_trades_per_day = max_trades_per_day
        self.cooldown_seconds = cooldown_seconds

        self._daily_pnl: float = 0.0
        self._trades_today: int = 0
        self._last_trade_ts: float = 0.0

    def can_open_position(
        self,
        current_position_size: float,
        new_order_size: float,
    ) -> RiskCheckResult:
        """Check whether opening a new position of new_order_size is allowed."""

        # Daily loss limit
        if self._daily_pnl <= -self.max_daily_loss:
            return RiskCheckResult(
                allowed=False,
                reason=f"Daily loss limit reached: {self._daily_pnl:.2f} <= -{self.max_daily_loss}",
            )

        # Daily trade cap
        if self._trades_today >= self.max_trades_per_day:
            return RiskCheckResult(
                allowed=False,
                reason=f"Daily trade limit reached: {self._trades_today} >= {self.max_trades_per_day}",
            )

        # Position size limit
        if current_position_size + new_order_size > self.max_position_size:
            return RiskCheckResult(
                allowed=False,
                reason=(
                    f"Position size would exceed limit: "
                    f"{current_position_size + new_order_size:.2f} > {self.max_position_size}"
                ),
            )

        # Cooldown
        now = time.time()
        if now - self._last_trade_ts < self.cooldown_seconds:
            wait = self.cooldown_seconds - (now - self._last_trade_ts)
            return RiskCheckResult(
                allowed=False,
                reason=f"Cooldown active: {wait:.0f}s remaining",
            )

        return RiskCheckResult(allowed=True, reason="ok")

    def record_trade(self, realized_pnl: float = 0.0) -> None:
        """Update internal counters after a trade is executed."""
        self._daily_pnl += realized_pnl
        self._trades_today += 1
        self._last_trade_ts = time.time()
        logger.info(
            f"Trade recorded: pnl_delta={realized_pnl:.2f} "
            f"daily_pnl={self._daily_pnl:.2f} trades={self._trades_today}"
        )

    def reset_daily(self) -> None:
        """Reset daily counters (call at start of new UTC day)."""
        self._daily_pnl = 0.0
        self._trades_today = 0
        logger.info("Daily risk counters reset")
