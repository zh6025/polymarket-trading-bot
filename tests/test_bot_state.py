"""
Tests for lib/bot_state.py
"""
import json
import os
import time
import pytest
import tempfile
from lib.bot_state import BotState


class TestBotStateSaveLoad:
    def test_save_and_load_roundtrip(self, tmp_path):
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = str(tmp_path / "state.json")
        state = BotState()
        state.trading_enabled = True
        state.total_pnl = 42.5
        state.daily_pnl = -5.0
        state.daily_trade_count = 7
        state.current_date = today  # use today so daily reset doesn't trigger
        state.save(path)

        loaded = BotState.load(path)
        assert loaded.trading_enabled is True
        assert loaded.total_pnl == 42.5
        assert loaded.daily_trade_count == 7

    def test_load_missing_file_returns_fresh_state(self, tmp_path):
        path = str(tmp_path / "nonexistent.json")
        state = BotState.load(path)
        assert state.total_pnl == 0.0
        assert state.daily_trade_count == 0
        assert state.current_date != ""

    def test_load_corrupted_file_returns_fresh_state(self, tmp_path):
        path = str(tmp_path / "corrupt.json")
        with open(path, 'w') as f:
            f.write("{not valid json")
        state = BotState.load(path)
        assert state.total_pnl == 0.0

    def test_atomic_write_no_partial_file(self, tmp_path):
        """Atomic write: .tmp file should not remain after save."""
        path = str(tmp_path / "state.json")
        state = BotState()
        state.save(path)
        assert os.path.exists(path)
        assert not os.path.exists(path + ".tmp")


class TestBotStateDailyReset:
    def test_daily_reset_on_date_change(self):
        state = BotState()
        state.current_date = "2020-01-01"
        state.daily_pnl = -15.0
        state.consecutive_losses = 3
        state.daily_trade_count = 10
        state.circuit_breaker = True

        state.check_daily_reset()

        today = __import__('datetime').datetime.now(
            __import__('datetime').timezone.utc
        ).strftime("%Y-%m-%d")
        assert state.current_date == today
        assert state.daily_pnl == 0.0
        assert state.consecutive_losses == 0
        assert state.daily_trade_count == 0
        assert state.circuit_breaker is False

    def test_no_reset_when_same_date(self):
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        state = BotState()
        state.current_date = today
        state.daily_pnl = -5.0
        state.check_daily_reset()
        assert state.daily_pnl == -5.0


class TestBotStateCanTrade:
    def setup_method(self):
        from datetime import datetime, timezone
        self.state = BotState()
        self.state.current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def test_trading_disabled_blocks_trade(self):
        self.state.trading_enabled = False
        ok, reason = self.state.can_trade()
        assert ok is False
        assert 'TRADING_ENABLED' in reason

    def test_trading_enabled_allows_trade(self):
        self.state.trading_enabled = True
        ok, reason = self.state.can_trade()
        assert ok is True

    def test_circuit_breaker_blocks_trade(self):
        self.state.trading_enabled = True
        self.state.circuit_breaker = True
        ok, reason = self.state.can_trade()
        assert ok is False
        assert '熔断' in reason

    def test_daily_loss_limit_triggers_circuit_breaker(self):
        self.state.trading_enabled = True
        self.state.daily_pnl = -25.0
        ok, reason = self.state.can_trade(daily_loss_limit=20)
        assert ok is False
        assert self.state.circuit_breaker is True

    def test_consecutive_loss_limit(self):
        self.state.trading_enabled = True
        self.state.consecutive_losses = 3
        ok, reason = self.state.can_trade(consec_loss_limit=3)
        assert ok is False
        assert '连续' in reason

    def test_record_trade_updates_counters(self):
        self.state.trading_enabled = True
        self.state.record_trade(pnl=-1.0)
        assert self.state.daily_trade_count == 1
        assert self.state.consecutive_losses == 1
        assert self.state.daily_pnl == -1.0

        self.state.record_trade(pnl=2.0)
        assert self.state.consecutive_losses == 0
        assert self.state.daily_trade_count == 2
