"""Tests for lib/bot_state.py"""
import json
import os
import tempfile
import pytest
from lib.bot_state import BotState, MarketPosition


class TestMarketPosition:
    def test_to_dict_from_dict_roundtrip(self):
        pos = MarketPosition(
            market_slug="btc-5m-123",
            outcome="UP",
            token_id="tok1",
            entry_price=0.58,
            size=5.0,
            entry_ts="2026-01-01T00:00:00+00:00",
        )
        d = pos.to_dict()
        pos2 = MarketPosition.from_dict(d)
        assert pos2.market_slug == pos.market_slug
        assert pos2.entry_price == pos.entry_price


class TestBotState:
    def _tmpfile(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(path)  # remove so load() returns fresh state
        return path

    def test_fresh_state_defaults(self):
        path = self._tmpfile()
        state = BotState.load(path)
        assert state.trading_enabled is False
        assert state.daily_pnl == 0.0
        assert state.consecutive_losses == 0

    def test_save_and_load_roundtrip(self):
        path = self._tmpfile()
        state = BotState.load(path)
        state.trading_enabled = True
        state.daily_pnl = -5.0
        state.consecutive_losses = 2
        state.save(path)

        state2 = BotState.load(path)
        assert state2.trading_enabled is True
        assert state2.daily_pnl == -5.0
        assert state2.consecutive_losses == 2
        os.unlink(path)

    def test_atomic_save_creates_no_tmp_on_success(self):
        path = self._tmpfile()
        state = BotState.load(path)
        state.save(path)
        assert os.path.exists(path)
        assert not os.path.exists(path + ".tmp")
        os.unlink(path)

    def test_load_returns_fresh_on_corrupt_file(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.write(fd, b"{{{{not json")
        os.close(fd)
        state = BotState.load(path)
        assert state.daily_pnl == 0.0
        os.unlink(path)

    def test_record_trade_updates_pnl_and_counters(self):
        state = BotState()
        state.record_trade(2.5)
        assert state.daily_pnl == 2.5
        assert state.daily_trade_count == 1
        assert state.consecutive_losses == 0

        state.record_trade(-1.0)
        assert state.daily_pnl == 1.5
        assert state.consecutive_losses == 1

        state.record_trade(1.0)
        assert state.consecutive_losses == 0

    def test_add_and_close_position(self):
        state = BotState()
        pos = MarketPosition(
            market_slug="mkt1", outcome="UP", token_id="t1",
            entry_price=0.60, size=3.0, entry_ts="ts",
        )
        state.add_open_position(pos)
        assert len(state.open_positions) == 1

        state.close_position("mkt1", exit_price=1.0, pnl=2.0)
        assert len(state.open_positions) == 0
        assert len(state.closed_positions) == 1
        assert state.closed_positions[0].pnl == 2.0

    def test_daily_reset_on_day_change(self):
        state = BotState()
        state.daily_pnl = -10.0
        state.daily_trade_count = 5
        state._day_key = "2000-01-01"  # force stale day
        state._maybe_reset_daily()
        assert state.daily_pnl == 0.0
        assert state.daily_trade_count == 0
