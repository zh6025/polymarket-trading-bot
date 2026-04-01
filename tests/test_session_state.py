"""
Tests for lib/session_state.py
"""
import time
import pytest
from lib.session_state import SessionState


def test_initial_state():
    s = SessionState()
    assert s.market_slug == ""
    assert s.has_position is False
    assert s.window0_processed is False
    assert s.window1_processed is False
    assert s.window2_processed is False
    assert s.mid_review_processed is False
    assert s.trade_executed is False


def test_reset_for_new_market():
    s = SessionState()
    s.market_slug = "old-market"
    s.window1_processed = True
    s.has_position = True
    s.position_direction = "UP"

    future_ts = time.time() + 300
    s.reset_for_new_market("new-market", future_ts)

    assert s.market_slug == "new-market"
    assert s.market_end_time == future_ts
    assert s.window1_processed is False
    assert s.has_position is False
    assert s.position_direction == ""
    assert s.trade_executed is False


def test_is_new_market():
    s = SessionState()
    s.market_slug = "btc-5m-123"
    assert s.is_new_market("btc-5m-456") is True
    assert s.is_new_market("btc-5m-123") is False


def test_seconds_remaining():
    s = SessionState()
    future = time.time() + 120
    s.market_end_time = future
    secs = s.seconds_remaining()
    assert 118.0 <= secs <= 121.0


def test_seconds_remaining_past_market():
    s = SessionState()
    s.market_end_time = time.time() - 10
    assert s.seconds_remaining() == 0.0


def test_open_position():
    s = SessionState()
    s.open_position(direction="UP", token_id="tok123", entry_price=0.62, size=3.0)
    assert s.has_position is True
    assert s.position_direction == "UP"
    assert s.position_token_id == "tok123"
    assert s.position_entry_price == 0.62
    assert s.position_size == 3.0
    assert s.trade_executed is True
    assert s.trade_direction == "UP"
    assert s.position_entry_time > 0


def test_close_position():
    s = SessionState()
    s.open_position("DOWN", "tok456", 0.70, 5.0)
    s.close_position(pnl=-0.5)
    assert s.has_position is False
    assert s.trade_pnl == -0.5


def test_full_lifecycle():
    """Simulate a complete market lifecycle"""
    s = SessionState()
    end_time = time.time() + 300
    s.reset_for_new_market("btc-5m-999", end_time)

    # Simulate entering at window 1
    s.window0_processed = True
    s.window1_processed = True
    s.open_position("UP", "token_up", 0.65, 3.0)

    assert s.has_position is True
    assert s.trade_executed is True

    # Simulate market expiry with settlement
    s.close_position(pnl=1.5)
    assert s.has_position is False
    assert s.trade_pnl == 1.5
