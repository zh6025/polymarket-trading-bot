"""
Tests for lib/hedge_formula.py
"""
import pytest
from lib.hedge_formula import (
    compute_min_hedge_quantity,
    check_strategy_feasibility,
    compute_profit_scenarios,
    compute_optimal_hedge,
    FEE_RATE,
)


class TestComputeMinHedgeQuantity:
    def test_standard_case(self):
        """P_m=0.55, Q_m=10, P_h=0.08"""
        Q_h = compute_min_hedge_quantity(P_m=0.55, Q_m=10, P_h=0.08, fee=FEE_RATE)
        expected = (0.55 * 10) / ((1 - 0.08) * (1 - FEE_RATE))
        assert abs(Q_h - expected) < 1e-9

    def test_zero_hedge_price_boundary(self):
        """P_h approaching 1.0 should produce large Q_h"""
        Q_h = compute_min_hedge_quantity(P_m=0.55, Q_m=10, P_h=0.99, fee=FEE_RATE)
        assert Q_h > 100

    def test_invalid_params_returns_inf(self):
        """P_h=1.0 makes denominator 0, should return inf"""
        Q_h = compute_min_hedge_quantity(P_m=0.55, Q_m=10, P_h=1.0, fee=0.0)
        assert Q_h == float('inf')

    def test_optimal_combo(self):
        """P_m=0.55, P_h=0.08 — most efficient combination"""
        Q_h = compute_min_hedge_quantity(P_m=0.55, Q_m=3.0, P_h=0.08, fee=FEE_RATE)
        assert Q_h > 0
        assert Q_h < 3.0  # hedge cost should be small


class TestCheckStrategyFeasibility:
    def test_feasible_case(self):
        """P_m=0.55, P_h=0.08 should be feasible"""
        result = check_strategy_feasibility(P_m=0.55, P_h=0.08, fee=FEE_RATE)
        assert result['feasible'] is True
        assert result['margin'] > 0
        assert result['lhs'] > result['rhs']

    def test_infeasible_case(self):
        """P_m=0.9, P_h=0.9 should be infeasible"""
        result = check_strategy_feasibility(P_m=0.9, P_h=0.9, fee=FEE_RATE)
        assert result['feasible'] is False

    def test_boundary_max_hedge_price(self):
        """max_hedge_price should be computed correctly"""
        result = check_strategy_feasibility(P_m=0.55, P_h=0.08, fee=FEE_RATE)
        max_p = result['max_hedge_price']
        assert 0 < max_p < 1.0
        # P_h=0.08 should be below max_hedge_price since strategy is feasible
        assert max_p > 0.08

    def test_details_string_contains_feasible(self):
        result = check_strategy_feasibility(P_m=0.55, P_h=0.08)
        assert '可行' in result['details'] or 'feasible' in result['details'].lower()

    def test_details_string_contains_infeasible(self):
        result = check_strategy_feasibility(P_m=0.95, P_h=0.95)
        assert '不可行' in result['details']


class TestComputeProfitScenarios:
    def test_main_wins(self):
        """When main position wins, profit should be positive for correct sizing"""
        result = compute_profit_scenarios(P_m=0.55, Q_m=10, P_h=0.08, Q_h=6.0)
        # main_wins_profit = Q_m*(1-P_m)*(1-fee) - P_h*Q_h
        expected = 10 * (1 - 0.55) * (1 - FEE_RATE) - 0.08 * 6.0
        assert abs(result['main_wins_profit'] - round(expected, 4)) < 1e-3

    def test_hedge_wins(self):
        """When hedge wins (main loses), profit formula should be correct"""
        result = compute_profit_scenarios(P_m=0.55, Q_m=10, P_h=0.08, Q_h=6.0)
        expected = 6.0 * (1 - 0.08) * (1 - FEE_RATE) - 0.55 * 10
        assert abs(result['hedge_wins_profit'] - round(expected, 4)) < 1e-3

    def test_total_cost(self):
        result = compute_profit_scenarios(P_m=0.55, Q_m=10, P_h=0.08, Q_h=6.0)
        expected_cost = 0.55 * 10 + 0.08 * 6.0
        assert abs(result['total_cost'] - round(expected_cost, 4)) < 1e-3

    def test_roi_pct_range(self):
        result = compute_profit_scenarios(P_m=0.55, Q_m=10, P_h=0.08, Q_h=6.0)
        assert isinstance(result['main_roi_pct'], float)
        assert isinstance(result['hedge_roi_pct'], float)


class TestComputeOptimalHedge:
    def test_feasible_returns_hedge_info(self):
        result = compute_optimal_hedge(P_m=0.55, Q_m=3.0, P_h=0.08)
        assert result['feasible'] is True
        assert result['hedge_quantity'] > 0
        assert result['hedge_cost'] > 0
        assert 'scenarios' in result

    def test_infeasible_returns_zero(self):
        result = compute_optimal_hedge(P_m=0.95, Q_m=3.0, P_h=0.95)
        assert result['feasible'] is False
        assert result['hedge_quantity'] == 0
        assert result['hedge_cost'] == 0

    def test_hedge_quantity_at_least_min(self):
        result = compute_optimal_hedge(P_m=0.55, Q_m=3.0, P_h=0.08)
        assert result['hedge_quantity'] >= result['min_hedge_quantity']

    def test_kelly_fraction_capped(self):
        result = compute_optimal_hedge(P_m=0.55, Q_m=3.0, P_h=0.08, win_prob=0.9)
        assert 0 <= result['kelly_fraction'] <= 0.5
