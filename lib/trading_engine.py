from dataclasses import dataclass
from typing import Optional


@dataclass
class BookLevel:
    price: float
    size: float


@dataclass
class OrderBookSnapshot:
    best_bid: Optional[BookLevel]
    best_ask: Optional[BookLevel]


@dataclass
class TradeSignal:
    should_buy_yes: bool
    should_buy_no: bool
    target_price: float
    order_size: float
    reason: str


class TradingEngine:
    def __init__(
        self,
        min_order_size: float,
        imbalance_threshold: float,
        min_spread: float,
    ):
        self.min_order_size = min_order_size
        self.imbalance_threshold = imbalance_threshold
        self.min_spread = min_spread

    def evaluate(self, yes_book: OrderBookSnapshot, no_book: OrderBookSnapshot) -> Optional[TradeSignal]:
        if not yes_book.best_bid or not yes_book.best_ask or not no_book.best_bid or not no_book.best_ask:
            return None

        yes_spread = yes_book.best_ask.price - yes_book.best_bid.price
        no_spread = no_book.best_ask.price - no_book.best_bid.price

        if yes_spread < self.min_spread and no_spread < self.min_spread:
            return None

        yes_bid_size = yes_book.best_bid.size
        yes_ask_size = yes_book.best_ask.size
        no_bid_size = no_book.best_bid.size
        no_ask_size = no_book.best_ask.size

        yes_imbalance = (yes_bid_size / yes_ask_size) if yes_ask_size > 0 else 0.0
        no_imbalance = (no_bid_size / no_ask_size) if no_ask_size > 0 else 0.0

        if yes_imbalance >= self.imbalance_threshold:
            return TradeSignal(
                should_buy_yes=True,
                should_buy_no=False,
                target_price=yes_book.best_ask.price,
                order_size=self.min_order_size,
                reason="yes_bid_ask_imbalance",
            )

        if no_imbalance >= self.imbalance_threshold:
            return TradeSignal(
                should_buy_yes=False,
                should_buy_no=True,
                target_price=no_book.best_ask.price,
                order_size=self.min_order_size,
                reason="no_bid_ask_imbalance",
            )

        return None
    def get_statistics(self) -> dict:
        return {
            "total_orders": 0,
            "filled_orders": 0,
            "total_trades": 0,
            "unrealized_pnl": 0.0,
        }
