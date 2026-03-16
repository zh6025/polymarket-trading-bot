"""Market state machine.

Each 5-minute BTC Up/Down market goes through the following states:

    OBSERVE
      │  Price divergence >= threshold AND trend != NEUTRAL
      ▼
    ENTERED  (initial 1 USDC position placed)
      │  Either:
      │   - ask < 0.20 AND > 60 s to end  → OPPORTUNITY_BUY_DONE
      │   - trend reversal                → EXIT (sell)
      │   - < 60 s to end                → FINAL_MINUTE
      ▼
    OPPORTUNITY_BUY_DONE  (2nd position placed)
      │  Either:
      │   - opportunity position price > 0.40  → take-profit sell
      │   - trend reversal on initial position → EXIT (sell all)
      │   - < 60 s to end                      → FINAL_MINUTE
      ▼
    FINAL_MINUTE
      │  Decision: sell all or hold to settlement
      ▼
    EXITED  (terminal; begin next market cycle)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from polymarket.models import MarketInfo, Order, OrderBook, Outcome

logger = logging.getLogger(__name__)


class MarketState(str, Enum):
    OBSERVE = "OBSERVE"
    ENTERED = "ENTERED"
    OPPORTUNITY_BUY_DONE = "OPPORTUNITY_BUY_DONE"
    FINAL_MINUTE = "FINAL_MINUTE"
    EXITED = "EXITED"


@dataclass
class MarketSession:
    """Mutable state for a single 5-minute market cycle."""

    market: MarketInfo
    state: MarketState = MarketState.OBSERVE

    # The initial directional order
    initial_order: Optional[Order] = None
    initial_outcome: Optional[Outcome] = None
    initial_entry_price: float = 0.0

    # The opportunistic <0.20 order
    opportunity_order: Optional[Order] = None
    opportunity_outcome: Optional[Outcome] = None
    opportunity_entry_price: float = 0.0

    # Track realised PnL for this market (filled in as orders close)
    realised_pnl: float = 0.0

    # Timestamps
    state_changed_at: float = field(default_factory=time.time)

    def transition(self, new_state: MarketState) -> None:
        logger.info(
            "State transition %s → %s",
            self.state.value,
            new_state.value,
            extra={"market_id": self.market.market_id},
        )
        self.state = new_state
        self.state_changed_at = time.time()

    @property
    def seconds_to_end(self) -> float:
        return self.market.end_timestamp - time.time()

    @property
    def is_in_final_minute(self) -> bool:
        return self.seconds_to_end <= 60

    @property
    def has_opportunity_slot(self) -> bool:
        """True if the opportunity buy hasn't been used yet."""
        return self.opportunity_order is None

    @property
    def total_entries(self) -> int:
        count = 0
        if self.initial_order is not None:
            count += 1
        if self.opportunity_order is not None:
            count += 1
        return count
