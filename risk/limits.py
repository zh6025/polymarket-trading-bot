"""Risk limit enforcement.

Provides a circuit-breaker / risk manager that:
  - Enforces per-trade USDC notional limits
  - Tracks daily loss and halts trading when the limit is breached
  - Prevents more than MAX_ENTRIES_PER_MARKET per market
  - Provides an API-failure circuit breaker
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class RiskLimits:
    """Configuration for risk limits."""

    max_trade_usdc: float = 1.0
    daily_max_loss_usdc: float = 10.0
    max_entries_per_market: int = 2
    # Minimum remaining seconds in a market before new entries are blocked
    min_seconds_before_end: float = 60.0
    # Number of consecutive API failures before halting
    max_api_failures: int = 5
    # Daily reset timezone offset from UTC in hours (0 = UTC)
    daily_reset_tz_offset_hours: float = 0.0


@dataclass
class RiskManager:
    """Stateful risk manager that gates order placement."""

    limits: RiskLimits = field(default_factory=RiskLimits)
    _daily_loss: float = 0.0
    _market_entry_count: dict[str, int] = field(default_factory=dict)
    _api_failure_count: int = 0
    _halted: bool = False
    _halt_reason: str = ""
    _last_reset_day: str = ""  # ISO date string (YYYY-MM-DD) of last reset

    def __post_init__(self) -> None:
        self._check_and_reset()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_halted(self) -> bool:
        """True when trading is halted due to a risk limit breach."""
        self._check_and_reset()
        return self._halted

    @property
    def halt_reason(self) -> str:
        return self._halt_reason

    def update_daily_loss(self, loss_usdc: float) -> None:
        """Update the cumulative daily loss.  *loss_usdc* is positive for a loss."""
        self._daily_loss += loss_usdc
        logger.debug("Daily loss updated: %.4f USDC (limit: %.4f)", self._daily_loss, self.limits.daily_max_loss_usdc)
        if self._daily_loss >= self.limits.daily_max_loss_usdc:
            self._halt(
                f"Daily max loss {self.limits.daily_max_loss_usdc} USDC reached "
                f"(current: {self._daily_loss:.4f} USDC)"
            )

    def record_api_failure(self) -> None:
        """Increment the API failure counter; halt if limit exceeded."""
        self._api_failure_count += 1
        logger.warning(
            "API failure count: %d / %d",
            self._api_failure_count,
            self.limits.max_api_failures,
        )
        if self._api_failure_count >= self.limits.max_api_failures:
            self._halt(
                f"Too many consecutive API failures "
                f"({self._api_failure_count})"
            )

    def record_api_success(self) -> None:
        """Reset the API failure counter on a successful call."""
        self._api_failure_count = 0

    def can_enter(
        self,
        market_id: str,
        size_usdc: float,
        seconds_to_end: float,
    ) -> tuple[bool, str]:
        """Check whether a new entry is allowed.

        Returns:
            (allowed, reason_if_not)
        """
        self._check_and_reset()

        if self._halted:
            return False, self._halt_reason

        if size_usdc > self.limits.max_trade_usdc:
            return False, (
                f"Trade size {size_usdc} exceeds limit {self.limits.max_trade_usdc}"
            )

        if seconds_to_end < self.limits.min_seconds_before_end:
            return False, (
                f"Only {seconds_to_end:.0f}s to market end "
                f"(min {self.limits.min_seconds_before_end}s)"
            )

        count = self._market_entry_count.get(market_id, 0)
        if count >= self.limits.max_entries_per_market:
            return False, (
                f"Already {count} entries for market {market_id} "
                f"(max {self.limits.max_entries_per_market})"
            )

        return True, ""

    def record_entry(self, market_id: str) -> None:
        """Record that an entry has been placed for *market_id*."""
        self._market_entry_count[market_id] = (
            self._market_entry_count.get(market_id, 0) + 1
        )
        logger.info(
            "Entry recorded for market %s (count: %d)",
            market_id,
            self._market_entry_count[market_id],
        )

    def reset_market(self, market_id: str) -> None:
        """Clear per-market state when a market cycle ends."""
        self._market_entry_count.pop(market_id, None)

    def resume(self) -> None:
        """Manually resume trading (e.g. after daily reset or operator action)."""
        self._halted = False
        self._halt_reason = ""
        self._api_failure_count = 0
        logger.info("Risk manager: trading resumed")

    @property
    def daily_loss(self) -> float:
        return self._daily_loss

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _halt(self, reason: str) -> None:
        if not self._halted:
            logger.error("TRADING HALTED: %s", reason)
        self._halted = True
        self._halt_reason = reason

    def _check_and_reset(self) -> None:
        """Reset daily counters if the calendar day has rolled over."""
        tz_offset_hours = self.limits.daily_reset_tz_offset_hours
        import datetime as _dt
        tz = _dt.timezone(_dt.timedelta(hours=tz_offset_hours))
        now_local = datetime.now(tz)
        # Use ISO date string (YYYY-MM-DD) as a stable, unambiguous day key
        current_day_str = now_local.strftime("%Y-%m-%d")

        if not self._last_reset_day:
            self._last_reset_day = current_day_str
            return

        if current_day_str != self._last_reset_day:
            logger.info(
                "New day detected – resetting daily loss counter "
                "(previous: %.4f USDC)",
                self._daily_loss,
            )
            self._daily_loss = 0.0
            self._last_reset_day = current_day_str
            # Resume trading if halted only due to daily loss
            if self._halted and "Daily max loss" in self._halt_reason:
                self.resume()
