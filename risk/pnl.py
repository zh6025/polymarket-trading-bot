"""PnL tracking.

Tracks realised and unrealised profit/loss for the bot session.
PnL values are persisted via the storage layer; this module handles
in-memory accumulation and provides helpers for the strategy loop.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from polymarket.models import Fill, Order, OrderBook

logger = logging.getLogger(__name__)


@dataclass
class PnLTracker:
    """Per-session PnL tracker.

    All values in USDC.
    """

    daily_realised: float = 0.0
    session_realised: float = 0.0
    # Map order_id → cost basis (USDC spent)
    _open_positions: dict[str, float] = field(default_factory=dict)

    def record_fill(self, fill: Fill) -> None:
        """Record a fill and update cost basis / realised PnL accordingly."""
        cost = fill.price * fill.size
        if fill.side.value == "BUY":
            # Opening a position: track cost basis
            self._open_positions[fill.order_id] = (
                self._open_positions.get(fill.order_id, 0.0) + fill.size
            )
            logger.debug(
                "BUY fill recorded",
                extra={"order_id": fill.order_id, "cost": cost},
            )
        else:
            # Closing a position: realise PnL
            basis = self._open_positions.pop(fill.order_id, fill.size)
            pnl = (fill.price * fill.size) - basis
            self.daily_realised += pnl
            self.session_realised += pnl
            logger.info(
                "SELL fill: realised PnL %.4f USDC (daily total %.4f)",
                pnl,
                self.daily_realised,
                extra={"order_id": fill.order_id, "pnl": pnl},
            )

    def record_settlement(self, order_id: str, settled_price: float) -> None:
        """Mark a position as settled at *settled_price* (0 or 1)."""
        basis = self._open_positions.pop(order_id, 0.0)
        pnl = settled_price * basis - basis  # payoff - cost
        self.daily_realised += pnl
        self.session_realised += pnl
        logger.info(
            "Settlement: realised PnL %.4f USDC for order %s",
            pnl,
            order_id,
            extra={"order_id": order_id, "settled_price": settled_price},
        )

    def unrealised_pnl(
        self, order_id: str, current_mid: float, entry_price: float
    ) -> float:
        """Estimate unrealised PnL for an open position.

        Args:
            order_id: The order whose open position to evaluate.
            current_mid: Current mid price of the outcome token ($0..$1).
            entry_price: Price at which the position was opened.

        Returns:
            Estimated unrealised USDC PnL (positive = profit, negative = loss).
        """
        size_usdc = self._open_positions.get(order_id, 0.0)
        if entry_price <= 0:
            return 0.0
        token_size = size_usdc / entry_price
        return (current_mid - entry_price) * token_size

    def reset_daily(self) -> None:
        """Reset the daily PnL counter (call at UTC midnight)."""
        logger.info(
            "Daily PnL reset. Previous daily PnL: %.4f", self.daily_realised
        )
        self.daily_realised = 0.0
