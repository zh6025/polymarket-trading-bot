"""Tests for lib/decision.py"""
import pytest
from lib.decision import (
    compute_hedge_ratio,
    make_trade_decision,
    format_decision_log,
    SKIP, ENTER_MAIN_ONLY, ENTER_MAIN_AND_HEDGE,
)


class TestComputeHedgeRatio:
    def test_basic_ratio_clamped_to_max(self):
        # With high win_prob and low hedge_price, raw ratio is huge → capped at 0.35
        r = compute_hedge_ratio(main_price=0.90, hedge_price=0.05, win_prob=0.95)
        assert r == 0.35

    def test_basic_ratio_clamped_to_min(self):
        r = compute_hedge_ratio(main_price=0.01, hedge_price=0.99, win_prob=0.01)
        assert r == 0.05

    def test_reasonable_ratio(self):
        r = compute_hedge_ratio(main_price=0.55, hedge_price=0.10, win_prob=0.60)
        assert 0.05 <= r <= 0.35

    def test_invalid_hedge_price_returns_min(self):
        r = compute_hedge_ratio(main_price=0.5, hedge_price=1.0, win_prob=0.5)
        assert r == 0.05


class TestMakeTradeDecision:
    def _ok_params(self, **overrides):
        params = dict(
            seconds_remaining=200,
            min_remaining_seconds=90,
            main_ask=0.60,
            main_max_price=0.66,
            hedge_ask=0.10,
            hedge_max_price=0.25,
            spread_pct=0.02,
            max_spread_pct=0.05,
            depth_ok=True,
            hard_stop_secs=30,
            enable_hedge=False,
        )
        params.update(overrides)
        return params

    def test_hard_stop_triggers(self):
        d, r = make_trade_decision(**self._ok_params(seconds_remaining=20))
        assert d == SKIP
        assert "hard_stop" in r

    def test_min_remaining_triggers(self):
        d, r = make_trade_decision(**self._ok_params(seconds_remaining=50, min_remaining_seconds=90))
        assert d == SKIP
        assert "min_remaining" in r

    def test_main_price_too_high(self):
        d, r = make_trade_decision(**self._ok_params(main_ask=0.70, main_max_price=0.66))
        assert d == SKIP
        assert "main_price" in r

    def test_spread_too_high(self):
        d, r = make_trade_decision(**self._ok_params(spread_pct=0.10, max_spread_pct=0.05))
        assert d == SKIP
        assert "spread" in r

    def test_depth_fail(self):
        d, r = make_trade_decision(**self._ok_params(depth_ok=False))
        assert d == SKIP
        assert "depth" in r

    def test_enter_main_only(self):
        d, r = make_trade_decision(**self._ok_params(enable_hedge=False))
        assert d == ENTER_MAIN_ONLY

    def test_enter_main_and_hedge_when_enabled(self):
        d, r = make_trade_decision(**self._ok_params(enable_hedge=True, hedge_ask=0.10, hedge_max_price=0.25))
        assert d == ENTER_MAIN_AND_HEDGE

    def test_hedge_price_too_high_falls_back_to_main_only(self):
        d, r = make_trade_decision(**self._ok_params(enable_hedge=True, hedge_ask=0.30, hedge_max_price=0.25))
        assert d == ENTER_MAIN_ONLY


class TestFormatDecisionLog:
    def test_returns_string_with_required_fields(self):
        log = format_decision_log(1, "btc-5m-123", SKIP, "hard_stop", 0.60, 25)
        assert "cycle=1" in log
        assert "market=btc-5m-123" in log
        assert "decision=SKIP" in log

    def test_extra_fields(self):
        log = format_decision_log(2, "mkt", ENTER_MAIN_ONLY, "ok", 0.55, 150, extra={"foo": "bar"})
        assert "foo=bar" in log
