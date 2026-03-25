"""
Production decision strategy: momentum hedge with Kelly-optimal bet sizing.

Strategy logic:
  - Monitor YES/NO prices on BTC 5-minute binary markets.
  - When one side is ≥ momentum_threshold (default 0.70), enter on that side.
  - Apply Kelly criterion with an assumed momentum edge to size the main bet.
  - Optionally place a smaller hedge on the opposing side.
  - Skip if risk limits are exceeded (daily loss, consecutive losses, trade count).
"""

import logging
import math
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class DecisionResult:
    """Returned by ProductionDecisionStrategy.decide()."""
    decision: str                    # SKIP | ENTER_MAIN_ONLY | ENTER_MAIN_AND_HEDGE
    decision_reason: str
    main_token_id: str = ""
    main_outcome: str = ""           # YES or NO
    main_side: str = "buy"
    main_price: float = 0.0
    main_size: float = 0.0
    hedge_token_id: str = ""
    hedge_outcome: str = ""
    hedge_side: str = "buy"
    hedge_price: float = 0.0
    hedge_size: float = 0.0
    hedge_ratio: float = 0.0
    should_trade_hedge: bool = False
    skip_reasons: List[str] = field(default_factory=list)
    kelly_fraction: float = 0.0


class ProductionDecisionStrategy:
    """
    Momentum hedge decision strategy.

    Parameters (from config):
      momentum_threshold    – minimum price to trigger entry (default 0.70)
      edge_factor           – assumed probability edge over market (default 0.05)
      kelly_fraction_cap    – maximum Kelly fraction allowed (default 0.25)
      hedge_ratio           – fraction of main bet to place as hedge (default 0.30)
      enable_hedge          – whether to place the opposing hedge bet (default True)
      min_order_size        – minimum USDC per bet (default 3.0)
      max_order_size        – maximum USDC per bet (default 50.0)
      daily_loss_limit_usdc – halt trading above this daily loss (default 20)
      daily_trade_limit     – max trades per calendar day (default 20)
      consecutive_loss_limit – halt after N consecutive losses (default 3)
    """

    def __init__(self, config=None):
        self.config = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def decide(self, market_data: dict, bot_state, config=None) -> DecisionResult:
        """
        Analyse market_data and bot_state; return a DecisionResult.

        market_data keys expected:
          yes_price, no_price, yes_token_id, no_token_id
        """
        cfg = config or self.config
        skip_reasons = []

        # Risk guard: bot halted
        if bot_state.is_halted:
            return DecisionResult(
                decision="SKIP",
                decision_reason="Bot is halted",
                skip_reasons=[f"halted: {bot_state.halt_reason}"],
            )

        # Risk guard: daily loss limit
        daily_loss_limit = getattr(cfg, "daily_loss_limit_usdc", 20)
        if bot_state.daily_pnl <= -abs(daily_loss_limit):
            return DecisionResult(
                decision="SKIP",
                decision_reason="Daily loss limit reached",
                skip_reasons=[f"daily_pnl={bot_state.daily_pnl:.2f} <= -{daily_loss_limit}"],
            )

        # Risk guard: consecutive losses
        consec_limit = getattr(cfg, "consecutive_loss_limit", 3)
        if bot_state.consecutive_losses >= consec_limit:
            return DecisionResult(
                decision="SKIP",
                decision_reason="Consecutive loss limit reached",
                skip_reasons=[f"consecutive_losses={bot_state.consecutive_losses}"],
            )

        # Risk guard: daily trade limit
        trade_limit = getattr(cfg, "daily_trade_limit", 20)
        if bot_state.daily_trade_count >= trade_limit:
            return DecisionResult(
                decision="SKIP",
                decision_reason="Daily trade limit reached",
                skip_reasons=[f"daily_trade_count={bot_state.daily_trade_count}"],
            )

        # Extract prices
        yes_price = float(market_data.get("yes_price") or 0.0)
        no_price = float(market_data.get("no_price") or 0.0)
        yes_token_id = market_data.get("yes_token_id", "")
        no_token_id = market_data.get("no_token_id", "")

        if yes_price is None or no_price is None or yes_price <= 0 or no_price <= 0:
            return DecisionResult(
                decision="SKIP",
                decision_reason="Invalid or missing prices",
                skip_reasons=["prices unavailable"],
            )

        threshold = getattr(cfg, "momentum_threshold", 0.70)
        min_size = getattr(cfg, "min_order_size", 3.0)
        max_size = getattr(cfg, "max_order_size", 50.0)
        edge_factor = getattr(cfg, "edge_factor", 0.05)
        kelly_cap = getattr(cfg, "kelly_fraction_cap", 0.25)
        hedge_ratio = getattr(cfg, "hedge_ratio", 0.30)
        enable_hedge = getattr(cfg, "enable_hedge", True)
        bankroll = getattr(cfg, "bankroll", 100.0)

        # Determine which side (if any) triggers momentum entry
        main_price = None
        main_token_id = ""
        main_outcome = ""
        hedge_token_id = ""
        hedge_outcome = ""
        hedge_price = 0.0

        if yes_price >= threshold and yes_price >= no_price:
            main_price = yes_price
            main_token_id = yes_token_id
            main_outcome = "YES"
            hedge_token_id = no_token_id
            hedge_outcome = "NO"
            hedge_price = no_price
        elif no_price >= threshold:
            main_price = no_price
            main_token_id = no_token_id
            main_outcome = "NO"
            hedge_token_id = yes_token_id
            hedge_outcome = "YES"
            hedge_price = yes_price
        else:
            return DecisionResult(
                decision="SKIP",
                decision_reason=f"No side above threshold {threshold:.0%}",
                skip_reasons=[f"yes={yes_price:.3f}, no={no_price:.3f}, threshold={threshold:.2f}"],
            )

        # Calculate Kelly fraction for main bet
        kelly = self._kelly_fraction(main_price, edge_factor, kelly_cap)
        main_size = self._bet_size(bankroll, kelly, min_size, max_size)

        if main_size < min_size:
            return DecisionResult(
                decision="SKIP",
                decision_reason="Calculated bet size below minimum",
                skip_reasons=[f"main_size={main_size:.2f} < min={min_size}"],
                kelly_fraction=kelly,
            )

        # Hedge sizing
        h_size = round(main_size * hedge_ratio, 2)
        should_hedge = enable_hedge and h_size >= min_size and hedge_price > 0

        decision = "ENTER_MAIN_AND_HEDGE" if should_hedge else "ENTER_MAIN_ONLY"
        reason = (
            f"Momentum: {main_outcome} at {main_price:.3f} (>{threshold:.0%}), "
            f"Kelly={kelly:.3f}, main={main_size:.2f} USDC"
        )
        if should_hedge:
            reason += f", hedge={h_size:.2f} USDC on {hedge_outcome}"

        return DecisionResult(
            decision=decision,
            decision_reason=reason,
            main_token_id=main_token_id,
            main_outcome=main_outcome,
            main_side="buy",
            main_price=main_price,
            main_size=main_size,
            hedge_token_id=hedge_token_id,
            hedge_outcome=hedge_outcome,
            hedge_side="buy",
            hedge_price=hedge_price,
            hedge_size=h_size if should_hedge else 0.0,
            hedge_ratio=hedge_ratio,
            should_trade_hedge=should_hedge,
            kelly_fraction=kelly,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _kelly_fraction(market_price: float, edge_factor: float, cap: float) -> float:
        """
        Calculate Kelly fraction assuming true probability = market_price + edge_factor.

        Kelly formula: f* = (p*b - q) / b
          where b = net odds per unit bet = (1 - price) / price
                p = assumed true probability
                q = 1 - p
        """
        true_p = min(market_price + edge_factor, 0.99)
        if market_price >= 1.0 or market_price <= 0.0:
            return 0.0
        b = (1.0 - market_price) / market_price
        if b <= 0:
            return 0.0
        q = 1.0 - true_p
        kelly = (true_p * b - q) / b
        kelly = max(0.0, kelly)
        return min(kelly, cap)

    @staticmethod
    def _bet_size(bankroll: float, kelly: float, min_size: float, max_size: float) -> float:
        """Convert Kelly fraction to a USDC bet size."""
        raw = bankroll * kelly
        return round(max(min_size, min(raw, max_size)), 2)
