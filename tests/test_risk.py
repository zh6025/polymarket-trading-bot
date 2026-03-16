"""Unit tests for risk management."""
from __future__ import annotations

import pytest

from risk.limits import RiskLimits, RiskManager


def make_risk(**kwargs) -> RiskManager:
    limits = RiskLimits(**kwargs)
    return RiskManager(limits=limits)


class TestRiskManagerCanEnter:
    def test_basic_allowed(self):
        rm = make_risk()
        allowed, _ = rm.can_enter("mkt1", 1.0, seconds_to_end=120)
        assert allowed is True

    def test_exceeds_per_trade_limit(self):
        rm = make_risk(max_trade_usdc=1.0)
        allowed, reason = rm.can_enter("mkt1", 2.0, seconds_to_end=120)
        assert allowed is False
        assert "size" in reason.lower() or "exceeds" in reason.lower()

    def test_too_close_to_end(self):
        rm = make_risk(min_seconds_before_end=60)
        allowed, reason = rm.can_enter("mkt1", 1.0, seconds_to_end=30)
        assert allowed is False
        assert "end" in reason.lower()

    def test_max_entries_per_market(self):
        rm = make_risk(max_entries_per_market=2)
        rm.record_entry("mkt1")
        rm.record_entry("mkt1")
        allowed, reason = rm.can_enter("mkt1", 1.0, seconds_to_end=120)
        assert allowed is False
        assert "entries" in reason.lower() or "max" in reason.lower()

    def test_halted(self):
        rm = make_risk(daily_max_loss_usdc=5.0)
        rm.update_daily_loss(5.0)  # triggers halt
        allowed, reason = rm.can_enter("mkt1", 1.0, seconds_to_end=120)
        assert allowed is False


class TestDailyLossLimit:
    def test_halt_on_breach(self):
        rm = make_risk(daily_max_loss_usdc=10.0)
        assert rm.is_halted is False
        rm.update_daily_loss(10.0)
        assert rm.is_halted is True

    def test_no_halt_below_limit(self):
        rm = make_risk(daily_max_loss_usdc=10.0)
        rm.update_daily_loss(9.99)
        assert rm.is_halted is False

    def test_cumulative_loss(self):
        rm = make_risk(daily_max_loss_usdc=10.0)
        rm.update_daily_loss(6.0)
        assert rm.is_halted is False
        rm.update_daily_loss(5.0)  # total now 11 > 10
        assert rm.is_halted is True


class TestApiCircuitBreaker:
    def test_halt_after_max_failures(self):
        rm = make_risk(max_api_failures=3)
        rm.record_api_failure()
        rm.record_api_failure()
        assert rm.is_halted is False
        rm.record_api_failure()
        assert rm.is_halted is True

    def test_reset_on_success(self):
        rm = make_risk(max_api_failures=3)
        rm.record_api_failure()
        rm.record_api_failure()
        rm.record_api_success()
        rm.record_api_failure()  # counter reset, so only 1 now
        assert rm.is_halted is False


class TestMarketEntryTracking:
    def test_entry_count_increments(self):
        rm = make_risk()
        rm.record_entry("mkt1")
        rm.record_entry("mkt1")
        assert rm._market_entry_count["mkt1"] == 2

    def test_reset_market_clears_count(self):
        rm = make_risk()
        rm.record_entry("mkt1")
        rm.reset_market("mkt1")
        assert rm._market_entry_count.get("mkt1", 0) == 0

    def test_different_markets_isolated(self):
        rm = make_risk(max_entries_per_market=2)
        rm.record_entry("mkt1")
        rm.record_entry("mkt1")
        # mkt2 should still be allowed
        allowed, _ = rm.can_enter("mkt2", 1.0, seconds_to_end=120)
        assert allowed is True
