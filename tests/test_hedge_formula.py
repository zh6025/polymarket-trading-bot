"""Tests for lib/hedge_formula.py"""
import pytest
from lib.hedge_formula import (
    min_hedge_quantity,
    is_strategy_viable,
    profit_if_correct,
    loss_if_wrong,
    kelly_optimal_hedge_ratio,
    scenario_summary,
    FEE_RATE,
)


class TestMinHedgeQuantity:
    def test_basic_calculation(self):
        # Q_h = (P_m * Q_m) / ((1 - P_h) * (1 - f))
        q_h = min_hedge_quantity(main_price=0.55, main_qty=10.0, hedge_price=0.10)
        expected = (0.55 * 10.0) / ((1 - 0.10) * (1 - FEE_RATE))
        assert abs(q_h - expected) < 1e-9

    def test_invalid_hedge_price_raises(self):
        with pytest.raises(ValueError):
            min_hedge_quantity(0.5, 10, hedge_price=1.0)

    def test_zero_fee(self):
        q_h = min_hedge_quantity(0.55, 10.0, 0.10, fee=0.0)
        expected = (0.55 * 10.0) / (0.90)
        assert abs(q_h - expected) < 1e-9


class TestIsStrategyViable:
    def test_viable_scenario(self):
        # P_m=0.55, P_h=0.10 → should be viable
        assert is_strategy_viable(0.55, 0.10) is True

    def test_not_viable_scenario(self):
        # P_m=0.90, P_h=0.90 → not viable
        assert is_strategy_viable(0.90, 0.90) is False

    def test_boundary_main_price(self):
        # P_m=0.65, P_h=0.15 → viable
        assert is_strategy_viable(0.65, 0.15) is True


class TestProfitIfCorrect:
    def test_positive_profit(self):
        pi = profit_if_correct(0.55, 10.0, 0.10, 1.0)
        # main wins: 10*(1-0.55)*(1-fee) − 0.10*1 = 10*0.45*0.98 − 0.10
        expected = 10 * 0.45 * (1 - FEE_RATE) - 0.10 * 1.0
        assert abs(pi - expected) < 1e-9

    def test_returns_positive_for_good_setup(self):
        pi = profit_if_correct(0.55, 10.0, 0.08, 0.8)
        assert pi > 0


class TestLossIfWrong:
    def test_near_zero_loss_with_good_hedge(self):
        # With correctly sized hedge, loss should be near 0
        main_price, main_qty, hedge_price = 0.55, 10.0, 0.10
        hedge_qty = min_hedge_quantity(main_price, main_qty, hedge_price)
        loss = loss_if_wrong(main_price, main_qty, hedge_price, hedge_qty)
        # Should be approximately 0 (break-even)
        assert abs(loss) < 0.1  # within 10 cents on a $10 position

    def test_loss_larger_than_breakeven_with_undersized_hedge(self):
        loss = loss_if_wrong(0.55, 10.0, 0.10, 0.5)  # hedge_qty too small
        assert loss < 0


class TestKellyOptimalHedgeRatio:
    def test_ratio_in_valid_range(self):
        r = kelly_optimal_hedge_ratio(win_prob=0.60, main_price=0.55)
        assert 0.05 <= r <= 0.50

    def test_higher_win_prob_lower_ratio(self):
        r_high = kelly_optimal_hedge_ratio(win_prob=0.85, main_price=0.55)
        r_low = kelly_optimal_hedge_ratio(win_prob=0.55, main_price=0.55)
        # Higher confidence → less hedge needed
        assert r_high <= r_low


class TestScenarioSummary:
    def test_keys_present(self):
        summary = scenario_summary(0.55, 10.0, 0.10, 1.0)
        for key in ("main_price", "hedge_price", "total_cost", "profit_if_correct",
                    "loss_if_wrong", "roi_pct", "strategy_viable"):
            assert key in summary

    def test_viable_flag_correct(self):
        summary_good = scenario_summary(0.55, 10.0, 0.10, 1.0)
        assert summary_good["strategy_viable"] is True

        summary_bad = scenario_summary(0.90, 10.0, 0.90, 1.0)
        assert summary_bad["strategy_viable"] is False
