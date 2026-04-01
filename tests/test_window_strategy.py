"""
Tests for lib/window_strategy.py
"""
import pytest
from lib.session_state import SessionState
from lib.market_bias import Bias
from lib.market_data import OrderbookSnapshot
from lib.window_strategy import (
    WindowDecision,
    evaluate_window0,
    evaluate_mid_review,
    evaluate_window1,
    evaluate_window2,
    run_window_strategy,
    WINDOW0_START, WINDOW0_END,
    MID_REVIEW_START, MID_REVIEW_END,
    WINDOW1_START, WINDOW1_END,
    WINDOW2_START, WINDOW2_END,
)


def make_session(has_position: bool = False, direction: str = "", token_id: str = "tok",
                 entry_price: float = 0.60, size: float = 3.0) -> SessionState:
    s = SessionState()
    if has_position:
        s.has_position = True
        s.position_direction = direction
        s.position_token_id = token_id
        s.position_entry_price = entry_price
        s.position_size = size
    return s


def make_ob(price: float, token_id: str = "tok_up", bid_depth: float = 100.0,
            ask_depth: float = 100.0, spread: float = 0.02) -> OrderbookSnapshot:
    return OrderbookSnapshot(
        token_id=token_id,
        timestamp=0.0,
        best_bid=price - spread / 2,
        best_ask=price + spread / 2,
        mid_price=price,
        bid_depth=bid_depth,
        ask_depth=ask_depth,
        spread=spread,
    )


# ─── Window 0 ────────────────────────────────────────────────────────────────

class TestWindow0:
    def test_disabled_by_default(self):
        s = make_session()
        ob = make_ob(0.72)
        result = evaluate_window0(s, 270, Bias.UP, ob, ob, 3.0, window0_enabled=False)
        assert result.action == 'SKIP'
        assert "window0_disabled" in result.reason

    def test_neutral_bias_skips(self):
        s = make_session()
        ob = make_ob(0.72)
        result = evaluate_window0(s, 270, Bias.NEUTRAL, ob, ob, 3.0, window0_enabled=True)
        assert result.action == 'SKIP'

    def test_price_above_cap_skips(self):
        s = make_session()
        ob = make_ob(0.90)
        result = evaluate_window0(s, 270, Bias.UP, ob, ob, 3.0, window0_enabled=True, hard_cap_price=0.85)
        assert result.action == 'SKIP'
        assert "above_cap" in result.reason

    def test_price_below_min_confidence_skips(self):
        s = make_session()
        ob = make_ob(0.50)
        result = evaluate_window0(s, 270, Bias.UP, ob, ob, 3.0, window0_enabled=True, min_confidence=0.70)
        assert result.action == 'SKIP'
        assert "too_low" in result.reason

    def test_valid_entry(self):
        s = make_session()
        ob_up = make_ob(0.75, token_id="tok_up")
        result = evaluate_window0(s, 270, Bias.UP, ob_up, None, 3.0,
                                   window0_enabled=True, min_confidence=0.70)
        assert result.action == 'ENTER'
        assert result.direction == 'UP'
        assert result.size == pytest.approx(3.0)  # uses configured bet_size directly

    def test_outside_window_skips(self):
        s = make_session()
        ob = make_ob(0.75)
        result = evaluate_window0(s, 200, Bias.UP, ob, ob, 3.0, window0_enabled=True)
        assert result.action == 'SKIP'
        assert "not_in_window0" in result.reason


# ─── Mid-review ───────────────────────────────────────────────────────────────

class TestMidReview:
    def test_no_position_skips(self):
        s = make_session(has_position=False)
        result = evaluate_mid_review(s, 120, Bias.DOWN, None, None)
        assert result.action == 'SKIP'
        assert "no_position" in result.reason

    def test_direction_flip_triggers_stop_loss(self):
        s = make_session(has_position=True, direction="UP", entry_price=0.65, size=3.0)
        ob_up = make_ob(0.55, token_id="tok_up")
        result = evaluate_mid_review(s, 120, Bias.DOWN, ob_up, None)
        assert result.action == 'STOP_LOSS'
        assert "direction_flip" in result.reason

    def test_same_direction_no_flip(self):
        s = make_session(has_position=True, direction="UP", entry_price=0.65, size=3.0)
        result = evaluate_mid_review(s, 120, Bias.UP, None, None)
        assert result.action == 'SKIP'
        assert "no_flip" in result.reason

    def test_neutral_bias_no_stop(self):
        s = make_session(has_position=True, direction="UP", entry_price=0.65, size=3.0)
        result = evaluate_mid_review(s, 120, Bias.NEUTRAL, None, None)
        assert result.action == 'SKIP'

    def test_outside_window_skips(self):
        s = make_session(has_position=True, direction="UP")
        result = evaluate_mid_review(s, 90, Bias.DOWN, None, None)
        assert result.action == 'SKIP'
        assert "not_in_mid_review" in result.reason


# ─── Window 1 ────────────────────────────────────────────────────────────────

class TestWindow1:
    def test_valid_entry_up(self):
        s = make_session()
        ob_up = make_ob(0.62, token_id="tok_up")
        result = evaluate_window1(s, 92, Bias.UP, ob_up, None, 3.0)
        assert result.action == 'ENTER'
        assert result.direction == 'UP'
        assert result.size == 3.0
        assert result.token_id == "tok_up"

    def test_valid_entry_down(self):
        s = make_session()
        ob_down = make_ob(0.65, token_id="tok_down")
        result = evaluate_window1(s, 92, Bias.DOWN, None, ob_down, 3.0)
        assert result.action == 'ENTER'
        assert result.direction == 'DOWN'

    def test_neutral_bias_skips(self):
        s = make_session()
        ob = make_ob(0.62)
        result = evaluate_window1(s, 92, Bias.NEUTRAL, ob, ob, 3.0)
        assert result.action == 'SKIP'

    def test_holding_position_skips(self):
        s = make_session(has_position=True, direction="UP")
        ob = make_ob(0.62)
        result = evaluate_window1(s, 92, Bias.UP, ob, ob, 3.0)
        assert result.action == 'SKIP'
        assert "already_holding" in result.reason

    def test_price_above_cap_skips(self):
        s = make_session()
        ob = make_ob(0.88)
        result = evaluate_window1(s, 92, Bias.UP, ob, None, 3.0)
        assert result.action == 'SKIP'
        assert "above_cap" in result.reason

    def test_spread_too_wide_skips(self):
        s = make_session()
        ob = make_ob(0.62, spread=0.10)
        result = evaluate_window1(s, 92, Bias.UP, ob, None, 3.0, max_spread=0.05)
        assert result.action == 'SKIP'
        assert "spread_too_wide" in result.reason

    def test_outside_window_skips(self):
        s = make_session()
        ob = make_ob(0.62)
        result = evaluate_window1(s, 50, Bias.UP, ob, None, 3.0)
        assert result.action == 'SKIP'
        assert "not_in_window1" in result.reason

    def test_already_processed_skips(self):
        s = make_session()
        s.window1_processed = True
        ob = make_ob(0.62)
        result = evaluate_window1(s, 92, Bias.UP, ob, None, 3.0)
        assert result.action == 'SKIP'
        assert "already_processed" in result.reason


# ─── Window 2 ────────────────────────────────────────────────────────────────

class TestWindow2:
    def test_stop_loss_on_flip(self):
        s = make_session(has_position=True, direction="UP", token_id="tok_up",
                         entry_price=0.65, size=3.0)
        ob_up = make_ob(0.50, token_id="tok_up")
        result = evaluate_window2(s, 32, Bias.DOWN, ob_up, None, 3.0)
        assert result.action == 'STOP_LOSS'
        assert "stop_loss" in result.reason

    def test_holding_no_flip_skips(self):
        s = make_session(has_position=True, direction="UP")
        result = evaluate_window2(s, 32, Bias.UP, None, None, 3.0)
        assert result.action == 'SKIP'
        assert "holding_no_flip" in result.reason

    def test_late_entry_strong_signal(self):
        s = make_session()
        ob_up = make_ob(0.72, token_id="tok_up")
        result = evaluate_window2(s, 32, Bias.UP, ob_up, None, 3.0,
                                   late_entry_min_price=0.65)
        assert result.action == 'ENTER'
        assert result.direction == 'UP'

    def test_late_entry_price_not_strong_enough(self):
        s = make_session()
        ob = make_ob(0.60)
        result = evaluate_window2(s, 32, Bias.UP, ob, None, 3.0,
                                   late_entry_min_price=0.65)
        assert result.action == 'SKIP'
        assert "not_strong_enough" in result.reason

    def test_outside_window_skips(self):
        s = make_session()
        ob = make_ob(0.72)
        result = evaluate_window2(s, 92, Bias.UP, ob, None, 3.0)
        assert result.action == 'SKIP'


# ─── run_window_strategy ─────────────────────────────────────────────────────

class TestRunWindowStrategy:
    def test_volatility_filter_blocks(self):
        s = make_session()
        ob = make_ob(0.62)
        result = run_window_strategy(s, 92, Bias.UP, ob, None, 3.0,
                                      recent_volatility=0.25, max_recent_volatility=0.20)
        assert result.action == 'SKIP'
        assert "volatility_filter" in result.reason

    def test_window1_entry(self):
        s = make_session()
        ob_up = make_ob(0.62, token_id="tok_up")
        result = run_window_strategy(s, 92, Bias.UP, ob_up, None, 3.0)
        assert result.action == 'ENTER'
        assert result.window == 1
        assert s.window1_processed is True

    def test_window2_stop_loss(self):
        s = make_session(has_position=True, direction="UP", token_id="tok_up",
                         entry_price=0.65, size=3.0)
        s.window1_processed = True
        ob_up = make_ob(0.50, token_id="tok_up")
        result = run_window_strategy(s, 32, Bias.DOWN, ob_up, None, 3.0)
        assert result.action == 'STOP_LOSS'
        assert result.window == 2
        assert s.window2_processed is True

    def test_no_active_window(self):
        s = make_session()
        ob = make_ob(0.62)
        result = run_window_strategy(s, 200, Bias.UP, ob, None, 3.0)
        assert result.action == 'SKIP'
        assert "no_active_window" in result.reason

    def test_window0_disabled_then_window1(self):
        """Window 0 is disabled, should fall through to window 1"""
        s = make_session()
        ob_up = make_ob(0.75, token_id="tok_up")
        # secs_remaining in window0 range — but since w0 disabled, nothing happens there
        # Test at window1 range
        result = run_window_strategy(s, 92, Bias.UP, ob_up, None, 3.0,
                                      window0_enabled=False)
        assert result.action == 'ENTER'
        assert result.window == 1

    def test_window1_marks_processed(self):
        s = make_session()
        ob_up = make_ob(0.62, token_id="tok_up")
        run_window_strategy(s, 92, Bias.UP, ob_up, None, 3.0)
        assert s.window1_processed is True

    def test_all_windows_processed_skips(self):
        s = make_session()
        s.window0_processed = True
        s.mid_review_processed = True
        s.window1_processed = True
        s.window2_processed = True
        ob = make_ob(0.62)
        result = run_window_strategy(s, 92, Bias.UP, ob, None, 3.0)
        assert result.action == 'SKIP'
