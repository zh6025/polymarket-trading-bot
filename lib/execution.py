"""
Execution layer: handles buy/sell order placement for the new single-side strategy.
Supports dry-run mode for testing.
"""
import logging
import time
from dataclasses import dataclass
from typing import Optional
from lib.window_strategy import WindowDecision

log = logging.getLogger(__name__)


@dataclass
class OrderResult:
    success: bool
    order_id: str
    direction: str
    token_id: str
    price: float
    size: float
    dry_run: bool
    error: Optional[str] = None
    timestamp: float = 0.0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()


def execute_decision(
    decision: WindowDecision,
    polymarket_client,
    dry_run: bool = True,
) -> Optional[OrderResult]:
    """
    Execute a WindowDecision via Polymarket.

    Args:
        decision: The decision to execute (ENTER or STOP_LOSS)
        polymarket_client: PolymarketClient instance
        dry_run: If True, simulate without placing real orders

    Returns:
        OrderResult or None if nothing to execute
    """
    if decision.action not in ('ENTER', 'STOP_LOSS'):
        return None

    side = 'BUY' if decision.action == 'ENTER' else 'SELL'

    log.info(
        f"{'[DRY RUN] ' if dry_run else ''}Executing {side} | "
        f"window={decision.window} dir={decision.direction} "
        f"price={decision.price:.4f} size={decision.size:.2f} "
        f"reason={decision.reason}"
    )

    if dry_run:
        return OrderResult(
            success=True,
            order_id=f"dry_run_{int(time.time())}_{decision.window}",
            direction=decision.direction,
            token_id=decision.token_id,
            price=decision.price,
            size=decision.size,
            dry_run=True,
        )

    try:
        result = polymarket_client.place_order(
            token_id=decision.token_id,
            side=side,
            price=decision.price,
            size=decision.size,
        )
        order_id = result.get('orderID', result.get('id', 'unknown'))
        log.info(f"Order placed: {order_id}")
        return OrderResult(
            success=True,
            order_id=order_id,
            direction=decision.direction,
            token_id=decision.token_id,
            price=decision.price,
            size=decision.size,
            dry_run=False,
        )
    except Exception as e:
        log.error(f"Order execution failed: {e}")
        return OrderResult(
            success=False,
            order_id='',
            direction=decision.direction,
            token_id=decision.token_id,
            price=decision.price,
            size=decision.size,
            dry_run=False,
            error=str(e),
        )
