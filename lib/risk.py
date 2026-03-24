from typing import Dict, Any, Optional
from lib.utils import log_warn, log_info


class RiskManager:
    """Risk Management Module"""

    def __init__(self, config: Any):
        self.config = config
        self.daily_loss = 0.0
        self.positions: Dict[str, Dict[str, Any]] = {}
        self.market_positions: Dict[str, Dict[str, Any]] = {}
        self.circuit_breaker_triggered = False
        self.consecutive_losses = 0
        self.daily_trade_count = 0
        self.last_trade_ts: Optional[int] = None

    def _cfg(self, key: str, default: Any = None) -> Any:
        if isinstance(self.config, dict):
            return self.config.get(key, default)
        return getattr(self.config, key, default)

    def is_trading_enabled(self) -> bool:
        return self._cfg("trading_enabled", False)

    def check_daily_loss_limit(self, current_pnl: float) -> bool:
        limit = self._cfg("daily_loss_limit_usdc", self._cfg("max_daily_loss", 20.0))

        if current_pnl <= -abs(limit):
            log_warn(f"⛔ Daily loss limit exceeded: {current_pnl} <= -{abs(limit)}")
            self.circuit_breaker_triggered = True
            return False

        return True

    def check_consecutive_loss_limit(self) -> bool:
        limit = self._cfg("consecutive_loss_limit", 3)

        if self.consecutive_losses >= limit:
            log_warn(f"⛔ Consecutive loss limit hit: {self.consecutive_losses} >= {limit}")
            self.circuit_breaker_triggered = True
            return False

        return True

    def check_daily_trade_limit(self) -> bool:
        limit = self._cfg("daily_trade_limit", self._cfg("max_trades_per_day", 20))

        if self.daily_trade_count >= limit:
            log_warn(f"⛔ Daily trade limit hit: {self.daily_trade_count} >= {limit}")
            return False

        return True

    def check_cooldown(self, now_ts: int) -> bool:
        cooldown = self._cfg("cooldown_seconds", 30)

        if self.last_trade_ts is None:
            return True

        if now_ts - self.last_trade_ts < cooldown:
            log_warn(f"⛔ Cooldown active: {now_ts - self.last_trade_ts}s < {cooldown}s")
            return False

        return True

    def can_open_market(self, market_id: str) -> bool:
        one_position_per_market = self._cfg("one_position_per_market", True)

        if not one_position_per_market:
            return True

        if market_id in self.market_positions:
            log_warn(f"⛔ Market already has position: {market_id}")
            return False

        return True

    def check_global_risk(
        self,
        market_id: str,
        current_pnl: float,
        now_ts: int,
    ) -> bool:
        if not self.is_trading_enabled():
            log_warn("⛔ Trading disabled")
            return False

        if self.circuit_breaker_triggered:
            log_warn("⛔ Circuit breaker already triggered")
            return False

        if not self.check_daily_loss_limit(current_pnl):
            return False

        if not self.check_consecutive_loss_limit():
            return False

        if not self.check_daily_trade_limit():
            return False

        if not self.check_cooldown(now_ts):
            return False

        if not self.can_open_market(market_id):
            return False

        return True

    def check_position_limit(self, outcome: str, size: float) -> bool:
        limit = self._cfg("max_position_size", 5000)

        current_pos = self.positions.get(outcome, {}).get("size", 0)

        if current_pos + size > limit:
            log_warn(f"⛔ Position limit exceeded for {outcome}: {current_pos + size} > {limit}")
            return False

        return True

    def check_remaining_time(self, remaining_sec: int, for_hedge: bool = False) -> bool:
        hard_stop = self._cfg("hard_stop_new_entry_sec", 30)
        min_main = self._cfg("min_secs_main_entry", 90)
        min_hedge = self._cfg("min_secs_hedge_entry", 60)

        if remaining_sec < hard_stop:
            log_warn(f"⛔ Remaining time below hard stop: {remaining_sec} < {hard_stop}")
            return False

        if for_hedge:
            if remaining_sec < min_hedge:
                log_warn(f"⛔ Remaining time below hedge minimum: {remaining_sec} < {min_hedge}")
                return False
        else:
            if remaining_sec < min_main:
                log_warn(f"⛔ Remaining time below main minimum: {remaining_sec} < {min_main}")
                return False

        return True

    def check_main_price(self, main_price: float) -> bool:
        min_main = self._cfg("min_main_price", 0.20)
        max_main = self._cfg("max_main_price", 0.66)

        if main_price < min_main:
            log_warn(f"⛔ Main price below minimum: {main_price} < {min_main}")
            return False

        if main_price > max_main:
            log_warn(f"⛔ Main price above maximum: {main_price} > {max_main}")
            return False

        return True

    def check_hedge_price(self, hedge_price: float) -> bool:
        min_hedge = self._cfg("min_hedge_price", 0.03)
        max_hedge = self._cfg("max_hedge_price", 0.25)

        if hedge_price < min_hedge:
            log_warn(f"⛔ Hedge price below minimum: {hedge_price} < {min_hedge}")
            return False

        if hedge_price > max_hedge:
            log_warn(f"⛔ Hedge price above maximum: {hedge_price} > {max_hedge}")
            return False

        return True

    def check_spread(self, spread: float, for_hedge: bool = False) -> bool:
        max_main_spread = self._cfg("max_main_spread", 0.03)
        max_hedge_spread = self._cfg("max_hedge_spread", 0.02)

        limit = max_hedge_spread if for_hedge else max_main_spread

        if spread > limit:
            log_warn(f"⛔ Spread too wide: {spread} > {limit}")
            return False

        return True

    def check_depth(self, depth_usdc: float, for_hedge: bool = False) -> bool:
        min_main_depth = self._cfg("min_main_depth_usdc", 10.0)
        min_hedge_depth = self._cfg("min_hedge_depth_usdc", 5.0)

        limit = min_hedge_depth if for_hedge else min_main_depth

        if depth_usdc < limit:
            log_warn(f"⛔ Depth too thin: {depth_usdc} < {limit}")
            return False

        return True

    def update_position(self, outcome: str, size: float, price: float):
        if outcome not in self.positions:
            self.positions[outcome] = {"size": 0.0, "avg_price": 0.0, "pnl": 0.0}

        pos = self.positions[outcome]
        total_size = pos["size"] + size

        if total_size != 0:
            pos["avg_price"] = (pos["size"] * pos["avg_price"] + size * price) / total_size
            pos["size"] = total_size
        else:
            pos["size"] = 0.0
            pos["avg_price"] = 0.0

    def record_market_open(
        self,
        market_id: str,
        outcome: str,
        size: float,
        price: float,
        now_ts: int,
        hedge_size: float = 0.0,
        hedge_price: float = 0.0,
    ):
        self.market_positions[market_id] = {
            "outcome": outcome,
            "size": size,
            "price": price,
            "hedge_size": hedge_size,
            "hedge_price": hedge_price,
            "opened_at": now_ts,
            "status": "OPEN",
        }
        self.daily_trade_count += 1
        self.last_trade_ts = now_ts
        self.update_position(outcome, size, price)

        log_info(
            f"✅ Recorded market open: market_id={market_id}, outcome={outcome}, "
            f"size={size}, price={price}, hedge_size={hedge_size}, hedge_price={hedge_price}"
        )

    def record_market_close(self, market_id: str, realized_pnl: float, now_ts: int):
        pos = self.market_positions.get(market_id)
        if not pos:
            return

        pos["status"] = "CLOSED"
        pos["closed_at"] = now_ts
        pos["realized_pnl"] = realized_pnl

        self.daily_loss += realized_pnl

        if realized_pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

        log_info(
            f"📊 Recorded market close: market_id={market_id}, realized_pnl={realized_pnl}, "
            f"daily_loss={self.daily_loss}, consecutive_losses={self.consecutive_losses}"
        )

    def calculate_total_pnl(self, current_prices: Dict[str, float]) -> float:
        total_pnl = 0.0

        for outcome, pos in self.positions.items():
            if pos["size"] != 0 and outcome in current_prices:
                pnl = pos["size"] * (current_prices[outcome] - pos["avg_price"])
                total_pnl += pnl

        return total_pnl

    def get_status(self) -> Dict[str, Any]:
        return {
            "trading_enabled": self.is_trading_enabled(),
            "circuit_breaker_triggered": self.circuit_breaker_triggered,
            "positions": self.positions,
            "market_positions": self.market_positions,
            "daily_loss": self.daily_loss,
            "consecutive_losses": self.consecutive_losses,
            "daily_trade_count": self.daily_trade_count,
            "last_trade_ts": self.last_trade_ts,
        }
