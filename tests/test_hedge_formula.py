"""
tests/test_hedge_formula.py

Unit tests for lib/hedge_formula.
"""
import unittest
from lib.hedge_formula import (
    FEE_RATE,
    compute_min_hedge_quantity,
    check_strategy_feasibility,
    compute_profit_scenarios,
    optimal_hedge_with_kelly,
)


class TestComputeMinHedgeQuantity(unittest.TestCase):
    """Tests for compute_min_hedge_quantity."""

    def test_basic_formula(self):
        """Q_h = P_m * Q_m / ((1 - P_h) * (1 - fee))"""
        P_m, Q_m, P_h = 0.60, 100.0, 0.10
        expected = (P_m * Q_m) / ((1 - P_h) * (1 - FEE_RATE))
        result = compute_min_hedge_quantity(P_m, Q_m, P_h)
        self.assertAlmostEqual(result, expected, places=8)

    def test_custom_fee(self):
        P_m, Q_m, P_h, fee = 0.55, 50.0, 0.08, 0.03
        expected = (P_m * Q_m) / ((1 - P_h) * (1 - fee))
        result = compute_min_hedge_quantity(P_m, Q_m, P_h, fee)
        self.assertAlmostEqual(result, expected, places=8)

    def test_zero_denominator_returns_zero(self):
        # P_h = 1.0 makes (1 - P_h) = 0
        result = compute_min_hedge_quantity(0.60, 100.0, 1.0)
        self.assertEqual(result, 0.0)

    def test_hedge_cost_covers_main_loss(self):
        """Hedge payout when hedge wins must be ≥ main bet cost."""
        P_m, Q_m, P_h = 0.60, 100.0, 0.10
        Q_h = compute_min_hedge_quantity(P_m, Q_m, P_h)
        # Hedge payout
        hedge_payout = Q_h * (1 - P_h) * (1 - FEE_RATE)
        # Main cost (what we paid for the main bet)
        main_cost = P_m * Q_m
        self.assertGreaterEqual(hedge_payout, main_cost - 1e-9)

    def test_proportional_to_main_quantity(self):
        """Doubling Q_m should double Q_h."""
        P_m, P_h = 0.60, 0.10
        q1 = compute_min_hedge_quantity(P_m, 50.0, P_h)
        q2 = compute_min_hedge_quantity(P_m, 100.0, P_h)
        self.assertAlmostEqual(q2 / q1, 2.0, places=8)

    def test_higher_main_price_increases_hedge(self):
        """Higher P_m (more costly main bet) → need larger hedge."""
        P_h, Q_m = 0.10, 100.0
        q_low  = compute_min_hedge_quantity(0.50, Q_m, P_h)
        q_high = compute_min_hedge_quantity(0.65, Q_m, P_h)
        self.assertGreater(q_high, q_low)

    def test_higher_hedge_price_increases_hedge(self):
        """Higher P_h (cheaper payout) → need more hedge quantity."""
        P_m, Q_m = 0.60, 100.0
        q_cheap  = compute_min_hedge_quantity(P_m, Q_m, P_h=0.05)
        q_costly = compute_min_hedge_quantity(P_m, Q_m, P_h=0.15)
        self.assertGreater(q_costly, q_cheap)


class TestCheckStrategyFeasibility(unittest.TestCase):
    """Tests for check_strategy_feasibility."""

    def test_typical_feasible(self):
        """Standard parameters (main=0.60, hedge=0.10) should be feasible."""
        result = check_strategy_feasibility(0.60, 0.10)
        self.assertTrue(result["feasible"])
        self.assertGreater(result["margin"], 0)

    def test_high_prices_infeasible(self):
        """When both prices are close to 0.5, the strategy is rarely feasible."""
        result = check_strategy_feasibility(0.50, 0.50)
        # (0.5)(0.5)(0.98)^2 = 0.2401  vs  0.5*0.5 = 0.25  → infeasible
        self.assertFalse(result["feasible"])

    def test_returns_required_keys(self):
        result = check_strategy_feasibility(0.60, 0.10)
        self.assertIn("feasible", result)
        self.assertIn("margin", result)
        self.assertIn("details", result)

    def test_margin_is_float(self):
        result = check_strategy_feasibility(0.60, 0.10)
        self.assertIsInstance(result["margin"], float)

    def test_feasibility_condition(self):
        """Verify the mathematical condition: (1-Pm)(1-Ph)(1-fee)^2 > Pm*Ph."""
        P_m, P_h, fee = 0.60, 0.10, 0.02
        lhs = (1 - P_m) * (1 - P_h) * ((1 - fee) ** 2)
        rhs = P_m * P_h
        result = check_strategy_feasibility(P_m, P_h, fee)
        self.assertEqual(result["feasible"], lhs > rhs)
        self.assertAlmostEqual(result["margin"], lhs - rhs, places=8)


class TestComputeProfitScenarios(unittest.TestCase):
    """Tests for compute_profit_scenarios."""

    def setUp(self):
        self.P_m  = 0.60
        self.Q_m  = 100.0
        self.P_h  = 0.10
        self.Q_h  = compute_min_hedge_quantity(self.P_m, self.Q_m, self.P_h)

    def test_returns_required_keys(self):
        result = compute_profit_scenarios(self.P_m, self.Q_m, self.P_h, self.Q_h)
        for key in ("main_wins_profit", "hedge_wins_profit", "expected_value", "max_loss"):
            self.assertIn(key, result)

    def test_main_wins_profit_formula(self):
        P_m, Q_m, P_h, Q_h, fee = 0.60, 100.0, 0.10, 50.0, 0.02
        expected = Q_m * (1 - P_m) * (1 - fee) - P_h * Q_h
        result = compute_profit_scenarios(P_m, Q_m, P_h, Q_h, fee)
        self.assertAlmostEqual(result["main_wins_profit"], expected, places=8)

    def test_hedge_wins_profit_formula(self):
        P_m, Q_m, P_h, Q_h, fee = 0.60, 100.0, 0.10, 50.0, 0.02
        expected = Q_h * (1 - P_h) * (1 - fee) - P_m * Q_m
        result = compute_profit_scenarios(P_m, Q_m, P_h, Q_h, fee)
        self.assertAlmostEqual(result["hedge_wins_profit"], expected, places=8)

    def test_expected_value_is_average(self):
        result = compute_profit_scenarios(self.P_m, self.Q_m, self.P_h, self.Q_h)
        ev_expected = (result["main_wins_profit"] + result["hedge_wins_profit"]) / 2
        self.assertAlmostEqual(result["expected_value"], ev_expected, places=8)

    def test_max_loss_is_minimum(self):
        result = compute_profit_scenarios(self.P_m, self.Q_m, self.P_h, self.Q_h)
        self.assertEqual(
            result["max_loss"],
            min(result["main_wins_profit"], result["hedge_wins_profit"]),
        )

    def test_min_hedge_breaks_even_on_hedge_win(self):
        """With min hedge quantity, hedge_wins_profit should be ≥ 0."""
        result = compute_profit_scenarios(self.P_m, self.Q_m, self.P_h, self.Q_h)
        self.assertGreaterEqual(result["hedge_wins_profit"], -1e-6)


class TestOptimalHedgeWithKelly(unittest.TestCase):
    """Tests for optimal_hedge_with_kelly."""

    def test_returns_required_keys(self):
        result = optimal_hedge_with_kelly(0.60, 100.0, 0.10, 0.40)
        for key in ("hedge_quantity", "hedge_cost", "kelly_fraction", "min_hedge_qty"):
            self.assertIn(key, result)

    def test_hedge_cost_equals_ph_times_quantity(self):
        P_h = 0.10
        result = optimal_hedge_with_kelly(0.60, 100.0, P_h, 0.40)
        expected_cost = P_h * result["hedge_quantity"]
        self.assertAlmostEqual(result["hedge_cost"], expected_cost, places=8)

    def test_min_hedge_qty_consistency(self):
        P_m, Q_m, P_h = 0.60, 100.0, 0.10
        result = optimal_hedge_with_kelly(P_m, Q_m, P_h, win_prob=0.40)
        expected_min = compute_min_hedge_quantity(P_m, Q_m, P_h)
        self.assertAlmostEqual(result["min_hedge_qty"], expected_min, places=8)

    def test_kelly_fraction_non_negative(self):
        for win_prob in [0.1, 0.3, 0.5, 0.7, 0.9]:
            result = optimal_hedge_with_kelly(0.60, 100.0, 0.10, win_prob)
            self.assertGreaterEqual(result["kelly_fraction"], 0.0)

    def test_hedge_quantity_at_least_min_when_kelly_positive(self):
        """When Kelly fraction > 0, hedge_quantity ≥ min_hedge_qty."""
        result = optimal_hedge_with_kelly(0.60, 100.0, 0.10, win_prob=0.70)
        if result["kelly_fraction"] > 0:
            self.assertGreaterEqual(result["hedge_quantity"], result["min_hedge_qty"] - 1e-9)

    def test_zero_p_h_returns_zero_hedge(self):
        result = optimal_hedge_with_kelly(0.60, 100.0, 0.0, 0.50)
        # Division by zero guard: kelly_fraction should be 0
        self.assertEqual(result["kelly_fraction"], 0.0)


class TestPriceWindowFiltering(unittest.TestCase):
    """Verify that ProductionDecisionStrategy enforces price windows."""

    def _make_scorer_result(self, direction="BUY_YES", prob=0.65, conf=0.30):
        return {
            "direction": direction,
            "probability": prob,
            "confidence": conf,
            "raw_score": 0.5,
            "signals": {},
        }

    def setUp(self):
        from lib.strategy import ProductionDecisionStrategy
        self.strategy = ProductionDecisionStrategy(
            min_confidence=0.15,
            main_price_min=0.50,
            main_price_max=0.65,
            hedge_price_min=0.05,
            hedge_price_max=0.15,
        )

    def test_enter_when_prices_in_window(self):
        result = self.strategy.decide(
            self._make_scorer_result("BUY_YES"), yes_mid=0.58, no_mid=0.10
        )
        self.assertEqual(result["action"], "ENTER")

    def test_skip_when_main_price_too_low(self):
        result = self.strategy.decide(
            self._make_scorer_result("BUY_YES"), yes_mid=0.40, no_mid=0.10
        )
        self.assertEqual(result["action"], "SKIP")

    def test_skip_when_main_price_too_high(self):
        result = self.strategy.decide(
            self._make_scorer_result("BUY_YES"), yes_mid=0.70, no_mid=0.10
        )
        self.assertEqual(result["action"], "SKIP")

    def test_skip_when_hedge_price_too_high(self):
        result = self.strategy.decide(
            self._make_scorer_result("BUY_YES"), yes_mid=0.58, no_mid=0.25
        )
        self.assertEqual(result["action"], "SKIP")

    def test_skip_when_confidence_too_low(self):
        result = self.strategy.decide(
            self._make_scorer_result("BUY_YES", conf=0.05),
            yes_mid=0.58, no_mid=0.10,
        )
        self.assertEqual(result["action"], "SKIP")

    def test_skip_when_scorer_says_skip(self):
        result = self.strategy.decide(
            self._make_scorer_result("SKIP", conf=0.30),
            yes_mid=0.58, no_mid=0.10,
        )
        self.assertEqual(result["action"], "SKIP")

    def test_buy_no_uses_no_as_main(self):
        """For BUY_NO direction, NO token becomes main, YES becomes hedge."""
        # no_mid=0.58 → valid main; yes_mid=0.10 → valid hedge
        result = self.strategy.decide(
            self._make_scorer_result("BUY_NO", prob=0.35, conf=0.30),
            yes_mid=0.10, no_mid=0.58,
        )
        self.assertEqual(result["action"], "ENTER")
        self.assertAlmostEqual(result["main_price"], 0.58)
        self.assertAlmostEqual(result["hedge_price"], 0.10)

    def test_result_keys_present(self):
        result = self.strategy.decide(
            self._make_scorer_result("BUY_YES"), yes_mid=0.58, no_mid=0.10
        )
        for key in ("action", "reason", "direction", "probability", "confidence",
                    "main_price", "hedge_price"):
            self.assertIn(key, result)


class TestExecutionOrder(unittest.TestCase):
    """Verify that bot_runner places hedge first, then main."""

    def test_hedge_placed_before_main(self):
        """
        When maybe_place_order is called, the first call should be the hedge
        and the second call the main order.
        """
        from unittest.mock import patch, MagicMock, call

        with patch("bot_runner.maybe_place_order") as mock_place:
            mock_place.return_value = {"status": "simulated"}

            from lib.config import Config
            from lib.polymarket_client import PolymarketClient
            from lib.strategy import ProductionDecisionStrategy
            import bot_runner

            config = MagicMock(spec=Config)
            config.dry_run = True
            config.order_size = 10.0
            config.fee_rate = 0.02
            config.scorer_enabled = False
            config.scorer_buy_threshold = 0.58
            config.scorer_sell_threshold = 0.42
            config.min_confidence = 0.0  # allow all
            config.main_price_min = 0.0
            config.main_price_max = 1.0
            config.hedge_price_min = 0.0
            config.hedge_price_max = 1.0

            # Build a minimal decision strategy that always says ENTER with BUY_YES
            decision_strategy = MagicMock(spec=ProductionDecisionStrategy)
            decision_strategy.decide.return_value = {
                "action": "ENTER",
                "reason": "test",
                "direction": "BUY_YES",
                "probability": 0.65,
                "confidence": 0.30,
                "main_price": 0.60,
                "hedge_price": 0.10,
            }

            client = MagicMock(spec=PolymarketClient)
            client.get_current_btc_5m_market.return_value = {
                "title": "test",
                "markets": [
                    {
                        "acceptingOrders": True,
                        "closed": False,
                        "outcome": "yes",
                        "outcomePrices": ["0.60", "0.40"],
                        "clobTokenIds": ["yes_token_id"],
                    },
                    {
                        "acceptingOrders": True,
                        "closed": False,
                        "outcome": "no",
                        "outcomePrices": ["0.40", "0.60"],
                        "clobTokenIds": ["no_token_id"],
                    },
                ],
            }
            client.get_orderbook.return_value = {
                "bids": [{"price": "0.59", "size": "10"}],
                "asks": [{"price": "0.61", "size": "10"}],
            }
            client.calculate_mid_price.side_effect = [
                {"bid": 0.59, "ask": 0.61, "mid": 0.60},
                {"bid": 0.09, "ask": 0.11, "mid": 0.10},
            ]

            bot_runner.run_cycle(config, client, decision_strategy, scorer=None)

            # Check that mock_place was called at least twice
            self.assertGreaterEqual(mock_place.call_count, 2)

            calls = mock_place.call_args_list
            # First call label should contain HEDGE
            first_label  = calls[0].kwargs.get("label", "")
            second_label = calls[1].kwargs.get("label", "")
            self.assertIn("HEDGE", first_label.upper())
            self.assertIn("MAIN",  second_label.upper())

    def test_main_not_placed_when_hedge_fails(self):
        """If the hedge fails, the main order must NOT be placed."""
        from unittest.mock import patch, MagicMock
        import bot_runner
        from lib.config import Config
        from lib.polymarket_client import PolymarketClient
        from lib.strategy import ProductionDecisionStrategy

        call_log = []

        def fake_place(client, token_id, side, price, size, dry_run, label):
            call_log.append(label)
            if "HEDGE" in label.upper():
                return None  # Hedge fails
            return {"status": "simulated"}

        with patch("bot_runner.maybe_place_order", side_effect=fake_place):
            config = MagicMock(spec=Config)
            config.dry_run = True
            config.order_size = 10.0
            config.fee_rate = 0.02
            config.scorer_enabled = False
            config.scorer_buy_threshold = 0.58
            config.scorer_sell_threshold = 0.42
            config.min_confidence = 0.0
            config.main_price_min = 0.0
            config.main_price_max = 1.0
            config.hedge_price_min = 0.0
            config.hedge_price_max = 1.0

            decision_strategy = MagicMock(spec=ProductionDecisionStrategy)
            decision_strategy.decide.return_value = {
                "action": "ENTER",
                "reason": "test",
                "direction": "BUY_YES",
                "probability": 0.65,
                "confidence": 0.30,
                "main_price": 0.60,
                "hedge_price": 0.10,
            }

            client = MagicMock(spec=PolymarketClient)
            client.get_current_btc_5m_market.return_value = {
                "markets": [
                    {
                        "acceptingOrders": True, "closed": False,
                        "outcome": "yes", "outcomePrices": ["0.60", "0.40"],
                        "clobTokenIds": ["yes_token_id"],
                    },
                    {
                        "acceptingOrders": True, "closed": False,
                        "outcome": "no", "outcomePrices": ["0.40", "0.60"],
                        "clobTokenIds": ["no_token_id"],
                    },
                ],
            }
            client.get_orderbook.return_value = {
                "bids": [{"price": "0.59", "size": "10"}],
                "asks": [{"price": "0.61", "size": "10"}],
            }
            client.calculate_mid_price.side_effect = [
                {"bid": 0.59, "ask": 0.61, "mid": 0.60},
                {"bid": 0.09, "ask": 0.11, "mid": 0.10},
            ]

            bot_runner.run_cycle(config, client, decision_strategy, scorer=None)

        # Only hedge was attempted; main must not appear
        main_calls = [label for label in call_log if "MAIN" in label.upper()]
        self.assertEqual(len(main_calls), 0, "Main order must not be placed when hedge fails")


if __name__ == "__main__":
    unittest.main()
