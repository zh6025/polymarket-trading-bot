"""
SessionState: Per-market session tracking for multi-window strategy.
Tracks which windows have been processed and current position within a 5-minute market.
"""
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SessionState:
    market_slug: str = ""
    market_end_time: float = 0.0  # unix timestamp when market closes

    # Window processing flags
    window0_processed: bool = False
    mid_review_processed: bool = False
    window1_processed: bool = False
    window2_processed: bool = False

    # Position tracking
    has_position: bool = False
    position_direction: str = ""   # 'UP' or 'DOWN'
    position_token_id: str = ""
    position_entry_price: float = 0.0
    position_size: float = 0.0
    position_entry_time: float = 0.0

    # Outcome
    trade_executed: bool = False
    trade_direction: str = ""
    trade_pnl: float = 0.0

    def reset_for_new_market(self, market_slug: str, market_end_time: float):
        """Reset session for a new 5-minute market"""
        self.market_slug = market_slug
        self.market_end_time = market_end_time
        self.window0_processed = False
        self.mid_review_processed = False
        self.window1_processed = False
        self.window2_processed = False
        self.has_position = False
        self.position_direction = ""
        self.position_token_id = ""
        self.position_entry_price = 0.0
        self.position_size = 0.0
        self.position_entry_time = 0.0
        self.trade_executed = False
        self.trade_direction = ""
        self.trade_pnl = 0.0

    def seconds_remaining(self, now: Optional[float] = None) -> float:
        """Seconds remaining until market close.
        
        Args:
            now: Current unix timestamp. Defaults to time.time(). Inject for testing.
        """
        if now is None:
            now = time.time()
        return max(0.0, self.market_end_time - now)

    def is_new_market(self, market_slug: str) -> bool:
        """Check if this is a different market than current session"""
        return self.market_slug != market_slug

    def open_position(self, direction: str, token_id: str, entry_price: float, size: float):
        """Record an opened position"""
        self.has_position = True
        self.position_direction = direction
        self.position_token_id = token_id
        self.position_entry_price = entry_price
        self.position_size = size
        self.position_entry_time = time.time()
        self.trade_executed = True
        self.trade_direction = direction

    def close_position(self, pnl: float = 0.0):
        """Record a closed position (stop-loss or expiry)"""
        self.has_position = False
        self.trade_pnl = pnl
