"""Risk management for the production single-shot bot runner."""

import logging
import time
from typing import Dict, Any

logger = logging.getLogger(__name__)


class RiskManager:
    """
    Per-run risk gatekeeper used by bot_runner.py.

    Accepts a config object (from lib.config.load_config) and checks
    whether entering a new position is safe given current PnL and state.
    """

    def __init__(self, config):
        self.config = config
        self._cooldown_ts: Dict[str, int] = {}

    def check_global_risk(
        self,
        market_id: str,
        current_pnl: float,
        now_ts: int,
    ) -> tuple:
        """
        Return (allowed: bool, reason: str).

        Checks:
        - Daily loss limit
        - Per-market cooldown
        - Consecutive loss limit (delegated to caller via state)
        """
        cfg = self.config

        # Daily loss limit
        if current_pnl <= -cfg.daily_loss_limit_usdc:
            reason = (
                f"Daily loss limit reached: pnl={current_pnl:.2f} "
                f"<= -{cfg.daily_loss_limit_usdc}"
            )
            logger.warning(reason)
            return False, reason

        # Cooldown check
        last_trade_ts = self._cooldown_ts.get(market_id, 0)
        if now_ts - last_trade_ts < cfg.cooldown_seconds:
            wait = cfg.cooldown_seconds - (now_ts - last_trade_ts)
            reason = f"Cooldown active for {market_id}: {wait}s remaining"
            logger.info(reason)
            return False, reason

        return True, "ok"

    def record_trade(self, market_id: str, now_ts: int) -> None:
        """Record that a trade was placed for cooldown tracking."""
        self._cooldown_ts[market_id] = now_ts
        logger.info(f"Trade recorded for market {market_id} at ts={now_ts}")
