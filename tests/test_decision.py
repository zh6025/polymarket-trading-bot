"""Tests for lib/decision.py – trade decision layer."""

import pytest
from lib.decision import (
    Decision,
    TradeDecision,
    compute_hedge_ratio,
    format_decision_log,
    make_trade_decision,
)


# ---------------------------------------------------------------------------
# compute_hedge_ratio
# ---------------------------------------------------------------------------

class TestComputeHedgeRatio:
    def test_zero_when_hedge_price_above_hard_max(self):
        ratio = compute_hedge_ratio(main_price=0.55, hedge_price=0.30, win_prob=0.60)
        assert ratio == 0.0

    def test_zero_when_hedge_price_is_zero(self):
        ratio = compute_hedge_ratio(main_price=0.55, hedge_price=0.0, win_prob=0.60)
        assert ratio == 0.0

    def test_zero_when_hedge_price_is_one(self):
        ratio = compute_hedge_ratio(main_price=0.55, hedge_price=1.0, win_prob=0.60)
        assert ratio == 0.0

    def test_positive_ratio_for_cheap_hedge(self):
        ratio = compute_hedge_ratio(main_price=0.55, hedge_price=0.15, win_prob=0.60)
        assert 0 < ratio <= 0.35

    def test_higher_win_prob_gives_lower_ratio(self):
        # Higher confidence → less hedging needed
        ratio_low = compute_hedge_ratio(main_price=0.55, hedge_price=0.15, win_prob=0.55)
        ratio_high = compute_hedge_ratio(main_price=0.55, hedge_price=0.15, win_prob=0.70)
        assert ratio_high < ratio_low

    def test_expensive_main_reduces_ratio(self):
        ratio_cheap = compute_hedge_ratio(main_price=0.45, hedge_price=0.15, win_prob=0.60)
        ratio_pricey = compute_hedge_ratio(main_price=0.64, hedge_price=0.15, win_prob=0.60)
        assert ratio_pricey < ratio_cheap

    def test_ratio_capped_at_max(self):
        # Very cheap hedge, very low win_prob → ratio should still be capped
        ratio = compute_hedge_ratio(
            main_price=0.50, hedge_price=0.01, win_prob=0.50,
            max_hedge_ratio=0.35
        )
        assert ratio <= 0.35

    def test_custom_hard_max(self):
        # hedge_price=0.20 is allowed by default (<=0.25) but not with custom hard_max=0.15
        ratio = compute_hedge_ratio(
            main_price=0.55, hedge_price=0.20, win_prob=0.60,
            hedge_price_hard_max=0.15
        )
        assert ratio == 0.0

    def test_example_scenario_1(self):
        """Pm=0.58, Ph=0.15, p=0.65 → ratio ≈ 0.106."""
        ratio = compute_hedge_ratio(0.58, 0.15, 0.65)
        assert abs(ratio - 0.1058) < 0.005

    def test_example_scenario_2(self):
        """Pm=0.60, Ph=0.20, p=0.60 → ratio ≈ 0.169."""
        ratio = compute_hedge_ratio(0.60, 0.20, 0.60)
        assert abs(ratio - 0.169) < 0.005


# ---------------------------------------------------------------------------
# make_trade_decision – SKIP paths
# ---------------------------------------------------------------------------

_BASE = dict(
    main_price=0.55,
    hedge_price=0.15,
    win_prob=0.60,
    remaining_sec=120.0,
    main_bet_size=3.0,
)


class TestMakeTradeDecisionSkip:
    def test_skip_when_last_30_seconds(self):
        d = make_trade_decision(**{**_BASE, "remaining_sec": 20.0})
        assert d.decision == Decision.SKIP
        assert d.reason == "remaining_below_hard_stop"

    def test_skip_when_below_min_main_entry(self):
        d = make_trade_decision(**{**_BASE, "remaining_sec": 60.0})
        assert d.decision == Decision.SKIP
        assert d.reason == "remaining_below_min_main_entry"

    def test_skip_when_main_price_too_high(self):
        d = make_trade_decision(**{**_BASE, "main_price": 0.70})
        assert d.decision == Decision.SKIP
        assert d.reason == "main_price_above_max"

    def test_skip_when_main_price_too_low(self):
        d = make_trade_decision(**{**_BASE, "main_price": 0.10})
        assert d.decision == Decision.SKIP
        assert d.reason == "main_price_below_min"

    def test_skip_when_main_spread_too_wide(self):
        d = make_trade_decision(**{**_BASE, "main_spread": 0.05})
        assert d.decision == Decision.SKIP
        assert d.reason == "main_spread_too_wide"

    def test_skip_when_main_depth_insufficient(self):
        d = make_trade_decision(**{**_BASE, "main_top_book_depth": 3.0})
        assert d.decision == Decision.SKIP
        assert d.reason == "main_depth_insufficient"

    def test_skip_exactly_at_hard_stop_boundary(self):
        d = make_trade_decision(**{**_BASE, "remaining_sec": 30.0})
        assert d.decision == Decision.SKIP

    def test_pass_just_above_hard_stop(self):
        d = make_trade_decision(**{**_BASE, "remaining_sec": 31.0})
        # remaining_sec=31 passes hard stop but may fail min_main_entry (default 90)
        assert d.decision == Decision.SKIP
        assert d.reason == "remaining_below_min_main_entry"


# ---------------------------------------------------------------------------
# make_trade_decision – ENTER_MAIN_ONLY paths
# ---------------------------------------------------------------------------

class TestMakeTradeDecisionMainOnly:
    def test_main_only_when_hedge_disabled(self):
        d = make_trade_decision(**{**_BASE, "enable_hedge": False})
        assert d.decision == Decision.ENTER_MAIN_ONLY
        assert d.hedge_ratio == 0.0
        assert d.hedge_size == 0.0
        assert d.main_size == _BASE["main_bet_size"]

    def test_main_only_when_hedge_price_above_max(self):
        d = make_trade_decision(**{**_BASE, "hedge_price": 0.28})
        assert d.decision == Decision.ENTER_MAIN_ONLY

    def test_main_only_when_hedge_time_insufficient(self):
        # remaining_sec=92 passes main (>=90) but might fail hedge (>=60 default passes,
        # but let's use a custom min_secs_hedge_entry that blocks it)
        d = make_trade_decision(**{**_BASE, "remaining_sec": 91.0, "min_secs_hedge_entry": 95.0})
        assert d.decision == Decision.ENTER_MAIN_ONLY

    def test_main_only_when_hedge_spread_too_wide(self):
        d = make_trade_decision(**{**_BASE, "hedge_spread": 0.05})
        assert d.decision == Decision.ENTER_MAIN_ONLY

    def test_main_only_when_hedge_depth_insufficient(self):
        d = make_trade_decision(**{**_BASE, "hedge_top_book_depth": 2.0})
        assert d.decision == Decision.ENTER_MAIN_ONLY


# ---------------------------------------------------------------------------
# make_trade_decision – ENTER_MAIN_AND_HEDGE paths
# ---------------------------------------------------------------------------

class TestMakeTradeDecisionMainAndHedge:
    def test_main_and_hedge_ideal_conditions(self):
        d = make_trade_decision(**_BASE)
        assert d.decision == Decision.ENTER_MAIN_AND_HEDGE
        assert d.hedge_ratio > 0.0
        assert d.hedge_size > 0.0
        assert d.main_size == _BASE["main_bet_size"]

    def test_hedge_size_equals_ratio_times_main(self):
        d = make_trade_decision(**_BASE)
        expected = round(_BASE["main_bet_size"] * d.hedge_ratio, 2)
        assert d.hedge_size == expected

    def test_metadata_contains_expected_keys(self):
        d = make_trade_decision(**_BASE)
        for key in ("main_price", "hedge_price", "win_prob", "remaining_sec", "main_bet_size", "hedge_ratio"):
            assert key in d.metadata

    def test_hedge_at_price_boundary(self):
        """hedge_price exactly at hedge_max_price (0.25) is included since the check is <=,
        so compute_hedge_ratio will return a positive value and a hedge may be entered."""
        d = make_trade_decision(**{**_BASE, "hedge_price": 0.25})
        assert d.decision in (Decision.ENTER_MAIN_ONLY, Decision.ENTER_MAIN_AND_HEDGE)


# ---------------------------------------------------------------------------
# format_decision_log
# ---------------------------------------------------------------------------

class TestFormatDecisionLog:
    def test_log_contains_market_slug(self):
        d = make_trade_decision(**_BASE)
        log = format_decision_log("btc-5m-123", "UP", "DOWN", d)
        assert "market=btc-5m-123" in log

    def test_log_contains_decision(self):
        d = make_trade_decision(**_BASE)
        log = format_decision_log("btc-5m-123", "UP", "DOWN", d)
        assert f"Decision={d.decision.value}" in log

    def test_log_contains_reason(self):
        d = make_trade_decision(**{**_BASE, "remaining_sec": 5.0})
        log = format_decision_log("btc-5m-123", "UP", "DOWN", d)
        assert "reason=" in log

    def test_skip_log_has_zero_sizes(self):
        d = make_trade_decision(**{**_BASE, "remaining_sec": 5.0})
        assert d.main_size == 0.0
        assert d.hedge_size == 0.0

    def test_str_representation(self):
        d = make_trade_decision(**_BASE)
        s = str(d)
        assert "Decision=" in s
        assert "reason=" in s
