"""Data models for the trading bot."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    LIVE = "LIVE"
    MATCHED = "MATCHED"
    CANCELLED = "CANCELLED"
    FILLED = "FILLED"


class Outcome(str, Enum):
    UP = "UP"
    DOWN = "DOWN"


@dataclass
class MarketInfo:
    """Information about a single Polymarket market (one outcome token)."""

    market_id: str          # conditionId or internal ID
    question: str
    token_id_up: str        # token id for UP outcome
    token_id_down: str      # token id for DOWN outcome
    end_date_iso: str       # ISO 8601 timestamp when market resolves
    end_timestamp: float    # unix timestamp
    active: bool = True
    slug: str = ""


@dataclass
class OrderBook:
    """Snapshot of the order book for a single outcome token."""

    token_id: str
    bids: list[tuple[float, float]] = field(default_factory=list)  # (price, size)
    asks: list[tuple[float, float]] = field(default_factory=list)  # (price, size)

    @property
    def best_bid(self) -> Optional[float]:
        return self.bids[0][0] if self.bids else None

    @property
    def best_ask(self) -> Optional[float]:
        return self.asks[0][0] if self.asks else None

    @property
    def mid(self) -> Optional[float]:
        if self.best_bid is not None and self.best_ask is not None:
            return (self.best_bid + self.best_ask) / 2
        return None


@dataclass
class Order:
    """A placed order."""

    order_id: str
    market_id: str
    token_id: str
    outcome: Outcome
    side: Side
    price: float
    size: float              # USDC notional
    status: OrderStatus = OrderStatus.PENDING
    filled_size: float = 0.0
    avg_fill_price: float = 0.0
    created_at: float = 0.0  # unix timestamp


@dataclass
class Fill:
    """A fill record."""

    fill_id: str
    order_id: str
    market_id: str
    token_id: str
    outcome: Outcome
    side: Side
    price: float
    size: float       # USDC notional filled
    timestamp: float  # unix timestamp


@dataclass
class Balance:
    """Account balance info."""

    usdc_available: float
    usdc_locked: float

    @property
    def total(self) -> float:
        return self.usdc_available + self.usdc_locked
