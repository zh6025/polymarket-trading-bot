"""Tests for lib/bot_state.py – BotState and MarketPosition."""

import json
import os
import tempfile
from datetime import date, datetime, timedelta

import pytest

from lib.bot_state import BotState, MarketPosition


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_position(market_id="mkt-001", main_side="UP", price=0.55, size=3.0):
    return MarketPosition(
        market_id=market_id,
        main_side=main_side,
        main_entry_price=price,
        main_size=size,
        hedge_side="DOWN",
        hedge_entry_price=0.15,
        hedge_size=0.99,
    )


# ---------------------------------------------------------------------------
# MarketPosition
# ---------------------------------------------------------------------------

class TestMarketPosition:
    def test_to_dict_and_from_dict_round_trip(self):
        pos = _make_position()
        d = pos.to_dict()
        restored = MarketPosition.from_dict(d)
        assert restored.market_id == pos.market_id
        assert restored.main_side == pos.main_side
        assert restored.main_entry_price == pos.main_entry_price
        assert restored.main_size == pos.main_size
        assert restored.hedge_side == pos.hedge_side

    def test_opened_at_is_set_automatically(self):
        pos = _make_position()
        assert pos.opened_at is not None
        # Should be parseable as ISO datetime
        datetime.fromisoformat(pos.opened_at)

    def test_optional_fields_default_to_none(self):
        pos = MarketPosition(
            market_id="mkt-002",
            main_side="DOWN",
            main_entry_price=0.45,
            main_size=2.0,
        )
        assert pos.closed_at is None
        assert pos.gross_pnl is None
        assert pos.net_pnl is None
        assert pos.winner is None
        assert pos.hedge_side is None


# ---------------------------------------------------------------------------
# BotState – daily counters
# ---------------------------------------------------------------------------

class TestBotStateDaily:
    def test_initial_state_defaults(self):
        s = BotState()
        assert s.trading_enabled is False
        assert s.daily_pnl == 0.0
        assert s.consecutive_losses == 0
        assert s.daily_trade_count == 0
        assert s.open_positions == {}
        assert s.closed_positions == []

    def test_reset_daily_counters_on_new_day(self, monkeypatch):
        s = BotState()
        s.daily_pnl = -15.0
        s.daily_trade_count = 10
        s.consecutive_losses = 2
        # Simulate yesterday as current_day
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        s.current_day = yesterday

        reset = s.reset_daily_counters_if_new_day()

        assert reset is True
        assert s.daily_pnl == 0.0
        assert s.daily_trade_count == 0
        assert s.consecutive_losses == 0
        assert s.current_day == date.today().isoformat()

    def test_no_reset_on_same_day(self):
        s = BotState()
        s.daily_pnl = -5.0
        s.current_day = date.today().isoformat()

        reset = s.reset_daily_counters_if_new_day()

        assert reset is False
        assert s.daily_pnl == -5.0


# ---------------------------------------------------------------------------
# BotState – position management
# ---------------------------------------------------------------------------

class TestBotStatePositions:
    def test_record_trade_open(self):
        s = BotState()
        pos = _make_position()
        s.record_trade_open(pos)

        assert s.has_open_position("mkt-001")
        assert s.daily_trade_count == 1

    def test_record_trade_open_duplicate_raises(self):
        s = BotState()
        s.record_trade_open(_make_position())

        with pytest.raises(ValueError, match="already open"):
            s.record_trade_open(_make_position())

    def test_record_trade_close_win(self):
        s = BotState()
        s.record_trade_open(_make_position())
        closed = s.record_trade_close("mkt-001", gross_pnl=1.5, net_pnl=1.2, winner="main")

        assert not s.has_open_position("mkt-001")
        assert s.daily_pnl == pytest.approx(1.2)
        assert s.consecutive_losses == 0
        assert len(s.closed_positions) == 1
        assert closed.net_pnl == 1.2

    def test_record_trade_close_loss_increments_consecutive(self):
        s = BotState()
        s.record_trade_open(_make_position("mkt-001"))
        s.record_trade_close("mkt-001", gross_pnl=-1.5, net_pnl=-1.5)

        assert s.consecutive_losses == 1

    def test_consecutive_losses_reset_on_win(self):
        s = BotState()

        for i in range(2):
            mid = f"mkt-{i:03d}"
            s.record_trade_open(_make_position(mid))
            s.record_trade_close(mid, gross_pnl=-1.0, net_pnl=-1.0)

        assert s.consecutive_losses == 2

        s.record_trade_open(_make_position("mkt-win"))
        s.record_trade_close("mkt-win", gross_pnl=2.0, net_pnl=1.8, winner="main")

        assert s.consecutive_losses == 0

    def test_record_close_missing_market_raises(self):
        s = BotState()
        with pytest.raises(KeyError):
            s.record_trade_close("nonexistent", gross_pnl=0, net_pnl=0)

    def test_closed_position_has_timestamps(self):
        s = BotState()
        s.record_trade_open(_make_position())
        closed = s.record_trade_close("mkt-001", gross_pnl=1.0, net_pnl=0.9)
        assert closed.closed_at is not None
        datetime.fromisoformat(closed.closed_at)


# ---------------------------------------------------------------------------
# BotState – serialisation
# ---------------------------------------------------------------------------

class TestBotStateSerialization:
    def test_to_dict_and_from_dict_round_trip(self):
        s = BotState()
        s.trading_enabled = True
        s.daily_pnl = 5.5
        s.consecutive_losses = 1
        s.record_trade_open(_make_position("mkt-a"))
        # daily_trade_count is 1 after record_trade_open; set it explicitly after
        s.daily_trade_count = 3

        d = s.to_dict()
        restored = BotState.from_dict(d)

        assert restored.trading_enabled is True
        assert restored.daily_pnl == pytest.approx(5.5)
        assert restored.consecutive_losses == 1
        assert restored.daily_trade_count == 3
        assert "mkt-a" in restored.open_positions

    def test_from_dict_with_closed_positions(self):
        s = BotState()
        s.record_trade_open(_make_position())
        s.record_trade_close("mkt-001", gross_pnl=1.0, net_pnl=0.9)

        d = s.to_dict()
        restored = BotState.from_dict(d)

        assert len(restored.closed_positions) == 1
        assert restored.closed_positions[0].market_id == "mkt-001"


# ---------------------------------------------------------------------------
# BotState – persistence
# ---------------------------------------------------------------------------

class TestBotStatePersistence:
    def test_save_and_load(self, tmp_path):
        path = str(tmp_path / "state.json")

        s = BotState()
        s.trading_enabled = True
        s.daily_pnl = -3.5
        s.record_trade_open(_make_position("mkt-x"))
        s.save(path)

        loaded = BotState.load(path)
        assert loaded.trading_enabled is True
        assert loaded.daily_pnl == pytest.approx(-3.5)
        assert "mkt-x" in loaded.open_positions

    def test_load_returns_fresh_state_when_file_missing(self, tmp_path):
        path = str(tmp_path / "nonexistent.json")
        s = BotState.load(path)
        assert s.daily_pnl == 0.0
        assert s.trading_enabled is False

    def test_load_returns_fresh_state_on_corrupt_file(self, tmp_path):
        path = str(tmp_path / "corrupt.json")
        with open(path, "w") as f:
            f.write("{ not valid json }")
        s = BotState.load(path)
        assert s.daily_pnl == 0.0

    def test_save_is_atomic(self, tmp_path):
        """Save should produce a valid JSON file (no .tmp remnant)."""
        path = str(tmp_path / "state.json")
        s = BotState()
        s.save(path)
        assert os.path.exists(path)
        assert not os.path.exists(path + ".tmp")
        with open(path) as f:
            data = json.load(f)
        assert "trading_enabled" in data

    def test_save_overwrites_previous(self, tmp_path):
        path = str(tmp_path / "state.json")

        s1 = BotState()
        s1.daily_pnl = 1.0
        s1.save(path)

        s2 = BotState()
        s2.daily_pnl = 2.0
        s2.save(path)

        loaded = BotState.load(path)
        assert loaded.daily_pnl == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# BotState – summary
# ---------------------------------------------------------------------------

class TestBotStateSummary:
    def test_summary_contains_key_fields(self):
        s = BotState()
        summary = s.summary()
        assert "trading_enabled" in summary
        assert "current_day" in summary
        assert "daily_pnl" in summary
        assert "daily_trade_count" in summary
        assert "consecutive_losses" in summary
        assert "open_positions" in summary
        assert "total_closed" in summary

    def test_summary_open_positions_is_list_of_ids(self):
        s = BotState()
        s.record_trade_open(_make_position("mkt-001"))
        s.record_trade_open(_make_position("mkt-002"))
        summary = s.summary()
        assert set(summary["open_positions"]) == {"mkt-001", "mkt-002"}
