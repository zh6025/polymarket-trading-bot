"""
Tests for lib/decision.py (simplified stub for new single-side architecture)
"""
import pytest
from lib.decision import make_trade_decision


def make_scorer_result(direction='BUY_YES', prob_up=0.65, total_score=20.0):
    return {
        'direction': direction,
        'prob_up': prob_up,
        'total_score': total_score,
        'confidence': 'HIGH',
    }


class TestHardStop:
    def test_hard_stop_blocks_trade(self):
        result = make_trade_decision(
            remaining_seconds=15,
            up_price=0.55,
            down_price=0.10,
            spread=0.02,
            depth=100,
            scorer_result=make_scorer_result(),
            hard_stop_sec=30,
        )
        assert result['action'] == 'SKIP'
        assert 'hard_stop' in result['reason']

    def test_above_hard_stop_proceeds(self):
        result = make_trade_decision(
            remaining_seconds=120,
            up_price=0.55,
            down_price=0.10,
            spread=0.02,
            depth=100,
            scorer_result=make_scorer_result(),
            hard_stop_sec=30,
            min_secs_main=90,
        )
        assert result['action'] != 'SKIP' or 'hard_stop' not in result['reason']


class TestMinTimeGate:
    def test_insufficient_time_skips(self):
        result = make_trade_decision(
            remaining_seconds=50,
            up_price=0.55,
            down_price=0.10,
            spread=0.02,
            depth=100,
            scorer_result=make_scorer_result(),
            hard_stop_sec=30,
            min_secs_main=90,
        )
        assert result['action'] == 'SKIP'
        assert 'insufficient_time' in result['reason']


class TestSignalGate:
    def test_skip_signal_skips(self):
        result = make_trade_decision(
            remaining_seconds=200,
            up_price=0.55,
            down_price=0.10,
            spread=0.02,
            depth=100,
            scorer_result=make_scorer_result(direction='SKIP', prob_up=0.5),
        )
        assert result['action'] == 'SKIP'
        assert 'no_signal' in result['reason']

    def test_low_confidence_skips(self):
        result = make_trade_decision(
            remaining_seconds=200,
            up_price=0.55,
            down_price=0.10,
            spread=0.02,
            depth=100,
            scorer_result=make_scorer_result(direction='BUY_YES', prob_up=0.52),
            min_confidence=0.15,
        )
        assert result['action'] == 'SKIP'
        assert 'low_confidence' in result['reason']


class TestPriceWindowGate:
    def test_main_price_out_of_window_skips(self):
        result = make_trade_decision(
            remaining_seconds=200,
            up_price=0.70,  # outside window [0.50, 0.65]
            down_price=0.10,
            spread=0.02,
            depth=100,
            scorer_result=make_scorer_result(direction='BUY_YES', prob_up=0.70),
            main_price_min=0.50,
            main_price_max=0.65,
        )
        assert result['action'] == 'SKIP'
        assert 'price_out_of_window' in result['reason']

    def test_main_price_in_window_proceeds(self):
        result = make_trade_decision(
            remaining_seconds=200,
            up_price=0.55,
            down_price=0.10,
            spread=0.02,
            depth=100,
            scorer_result=make_scorer_result(direction='BUY_YES', prob_up=0.65),
            main_price_min=0.50,
            main_price_max=0.65,
        )
        assert result['action'] in ('ENTER_MAIN_ONLY', 'ENTER_MAIN_AND_HEDGE')


class TestSpreadGate:
    def test_large_spread_skips(self):
        result = make_trade_decision(
            remaining_seconds=200,
            up_price=0.55,
            down_price=0.10,
            spread=0.10,  # above max_spread=0.05
            depth=100,
            scorer_result=make_scorer_result(direction='BUY_YES', prob_up=0.65),
            max_spread=0.05,
        )
        assert result['action'] == 'SKIP'
        assert 'spread_too_wide' in result['reason']


class TestDepthGate:
    def test_insufficient_depth_skips(self):
        result = make_trade_decision(
            remaining_seconds=200,
            up_price=0.55,
            down_price=0.10,
            spread=0.02,
            depth=10,  # below min_depth=50
            scorer_result=make_scorer_result(direction='BUY_YES', prob_up=0.65),
            min_depth=50,
        )
        assert result['action'] == 'SKIP'
        assert 'depth_insufficient' in result['reason']


class TestEntryDirection:
    def test_hedge_price_out_of_window_produces_main_only(self):
        result = make_trade_decision(
            remaining_seconds=200,
            up_price=0.55,
            down_price=0.40,  # not in hedge window
            spread=0.02,
            depth=100,
            scorer_result=make_scorer_result(direction='BUY_YES', prob_up=0.65),
            main_price_min=0.50,
            main_price_max=0.65,
            hedge_price_min=0.05,
            hedge_price_max=0.15,
        )
        assert result['action'] == 'ENTER_MAIN_ONLY'

    def test_buy_no_direction(self):
        """BUY_NO should set direction=DOWN and use down_price as main."""
        result = make_trade_decision(
            remaining_seconds=200,
            up_price=0.08,
            down_price=0.55,
            spread=0.02,
            depth=100,
            scorer_result=make_scorer_result(direction='BUY_NO', prob_up=0.30),
            main_price_min=0.50,
            main_price_max=0.65,
            hedge_price_min=0.05,
            hedge_price_max=0.15,
        )
        assert result['direction'] == 'DOWN'
        assert result['main_price'] == 0.55
