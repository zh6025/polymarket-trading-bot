"""Trading engine: order-book analysis and order execution."""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Any

from lib.utils import log_info, log_error, log_warn

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Order-book data structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class BookLevel:
    price: float
    size: float


@dataclass
class OrderBookSnapshot:
    best_bid: Optional[BookLevel]
    best_ask: Optional[BookLevel]


# ─────────────────────────────────────────────────────────────────────────────
# Signal returned by TradingEngine.evaluate()
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TradeSignal:
    should_buy_yes: bool
    order_size: float
    target_price: float
    reason: str


# ─────────────────────────────────────────────────────────────────────────────
# TradingEngine
# ─────────────────────────────────────────────────────────────────────────────

class TradingEngine:
    """
    Evaluates order-book snapshots and produces trade signals.

    Constructor signature is compatible with both usage patterns:
    - New style: TradingEngine(min_order_size, imbalance_threshold, min_spread)
    - Legacy:    TradingEngine(dry_run=True)  (kept for backward compatibility)
    """

    def __init__(
        self,
        min_order_size: float = 5.0,
        imbalance_threshold: float = 0.65,
        min_spread: float = 0.02,
        *,
        dry_run: bool = True,
    ):
        self.min_order_size = min_order_size
        self.imbalance_threshold = imbalance_threshold
        self.min_spread = min_spread
        self.dry_run = dry_run

        # Legacy tracking for backward compatibility
        self.orders: Dict[str, Dict] = {}
        self.positions: Dict[str, float] = {}
        self.trades: List[Dict] = []
        self.pnl: float = 0.0
        self.order_counter = 0

    # ── New-style interface ──────────────────────────────────────────────────

    def evaluate(
        self,
        yes_book: OrderBookSnapshot,
        no_book: OrderBookSnapshot,
    ) -> Optional[TradeSignal]:
        """
        Analyse YES and NO order books and return a TradeSignal or None.

        Returns None when:
        - Either book has no best bid/ask.
        - Spread is too wide.
        - No clear imbalance is detected.
        """
        if yes_book.best_bid is None or yes_book.best_ask is None:
            log_warn("YES book incomplete — skipping")
            return None
        if no_book.best_bid is None or no_book.best_ask is None:
            log_warn("NO book incomplete — skipping")
            return None

        yes_spread = yes_book.best_ask.price - yes_book.best_bid.price
        no_spread = no_book.best_ask.price - no_book.best_bid.price

        if yes_spread > self.min_spread * 3:
            log_warn(f"YES spread too wide: {yes_spread:.4f}")
            return None

        yes_mid = (yes_book.best_bid.price + yes_book.best_ask.price) / 2
        no_mid = (no_book.best_bid.price + no_book.best_ask.price) / 2

        # Order-book imbalance: compare bid sizes
        yes_bid_size = yes_book.best_bid.size
        no_bid_size = no_book.best_bid.size
        total = yes_bid_size + no_bid_size

        if total <= 0:
            return None

        yes_imbalance = yes_bid_size / total

        if yes_imbalance >= self.imbalance_threshold:
            return TradeSignal(
                should_buy_yes=True,
                order_size=self.min_order_size,
                target_price=yes_book.best_ask.price,
                reason=f"YES imbalance={yes_imbalance:.3f} mid={yes_mid:.4f}",
            )

        if (1 - yes_imbalance) >= self.imbalance_threshold:
            return TradeSignal(
                should_buy_yes=False,
                order_size=self.min_order_size,
                target_price=no_book.best_ask.price,
                reason=f"NO imbalance={1 - yes_imbalance:.3f} mid={no_mid:.4f}",
            )

        return None

    # ── Legacy interface (kept for backward compatibility) ───────────────────

    def place_order(
        self,
        token_id: str,
        side: str,
        price: float,
        size: float,
    ) -> str:
        self.order_counter += 1
        order_id = f"order_{self.order_counter}_{datetime.now().timestamp()}"
        order = {
            "id": order_id,
            "token_id": token_id,
            "side": side,
            "price": price,
            "size": size,
            "status": "filled" if self.dry_run else "pending",
            "timestamp": datetime.now().isoformat(),
            "filled_size": size if self.dry_run else 0,
            "avg_price": price if self.dry_run else 0,
        }
        self.orders[order_id] = order
        if self.dry_run:
            self._fill_order_legacy(order_id)
        log_info(f"Order placed: {side.upper()} {size:.2f} @ {price:.4f}")
        return order_id

    def _fill_order_legacy(self, order_id: str) -> None:
        order = self.orders.get(order_id)
        if not order:
            return
        token_id = order["token_id"]
        current_pos = self.positions.get(token_id, 0)
        if order["side"] == "buy":
            self.positions[token_id] = current_pos + order["size"]
        else:
            self.positions[token_id] = current_pos - order["size"]
        self.trades.append({
            "order_id": order_id,
            "token_id": token_id,
            "side": order["side"],
            "price": order["price"],
            "size": order["size"],
            "timestamp": order["timestamp"],
        })

    def get_statistics(self) -> Dict[str, Any]:
        filled = [o for o in self.orders.values() if o["status"] == "filled"]
        return {
            "total_orders": len(self.orders),
            "filled_orders": len(filled),
            "total_trades": len(self.trades),
            "positions": self.positions,
            "unrealized_pnl": self.pnl,
            "dry_run": self.dry_run,
        }
