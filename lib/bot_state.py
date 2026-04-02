"""
BotState: 全局状态管理，支持crash recovery
- 每日自动归零 daily counters
- 原子性 JSON 写入（write → rename）
- 持仓/损益/限频/硬停全链路风控
"""
import json
import os
import time
import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import List, Optional

log = logging.getLogger(__name__)


@dataclass
class MarketPosition:
    market_slug: str
    direction: str          # 'UP' or 'DOWN'
    token_id: str
    entry_price: float
    size: float
    entry_time: float       # unix timestamp
    hedge_token_id: Optional[str] = None
    hedge_price: Optional[float] = None
    hedge_size: Optional[float] = None
    pnl: float = 0.0
    closed: bool = False


@dataclass
class BotState:
    trading_enabled: bool = False
    daily_pnl: float = 0.0
    consecutive_losses: int = 0
    daily_trade_count: int = 0
    last_trade_time: float = 0
    current_date: str = ""
    open_positions: List[dict] = field(default_factory=list)
    closed_positions: List[dict] = field(default_factory=list)
    total_pnl: float = 0.0
    circuit_breaker: bool = False

    # ── Internal: not serialised ────────────────────────────────────────────
    # Path used for save(); set by load() so callers don't need to repeat it.
    _state_path: str = field(default="bot_state.json", repr=False, compare=False)

    def check_daily_reset(self):
        """UTC日切时自动归零"""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.current_date != today:
            log.info(f"📅 日切: {self.current_date} → {today}, 重置计数器")
            self.daily_pnl = 0.0
            self.consecutive_losses = 0
            self.daily_trade_count = 0
            self.circuit_breaker = False
            self.current_date = today

    def can_trade(self, daily_loss_limit: float = 20, daily_trade_limit: int = 20,
                  consec_loss_limit: int = 3) -> tuple:
        """检查是否允许交易"""
        self.check_daily_reset()
        if not self.trading_enabled:
            return False, "TRADING_ENABLED=false"
        if self.circuit_breaker:
            return False, "熔断器已触发"
        if self.daily_pnl <= -daily_loss_limit:
            self.circuit_breaker = True
            return False, f"日亏损超限: ${self.daily_pnl:.2f} <= -${daily_loss_limit}"
        if self.daily_trade_count >= daily_trade_limit:
            return False, f"日交易次数超限: {self.daily_trade_count} >= {daily_trade_limit}"
        if self.consecutive_losses >= consec_loss_limit:
            return False, f"连续亏损超限: {self.consecutive_losses} >= {consec_loss_limit}"
        return True, "OK"

    def record_trade(self, pnl: float):
        self.daily_trade_count += 1
        self.daily_pnl += pnl
        self.total_pnl += pnl
        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0
        self.last_trade_time = time.time()

    def save(self, path: Optional[str] = None):
        """原子写入"""
        if path is None:
            path = self._state_path
        # Ensure parent directory exists (e.g. data/ for data/bot_state.json)
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        # Guard against path being a directory (e.g. Docker volume mount of non-existent file).
        # Use rmdir (not shutil.rmtree) intentionally: only remove empty dirs.  If it has
        # contents something else is wrong and we must not silently delete data.
        if os.path.isdir(path):
            log.warning(f"State path '{path}' is a directory (likely Docker volume mount issue), removing it")
            try:
                os.rmdir(path)
            except OSError as e:
                log.error(f"Cannot remove directory '{path}': {e}")
                return
        tmp = path + ".tmp"
        try:
            data = asdict(self)
            data.pop('_state_path', None)  # internal field, not persisted
            with open(tmp, 'w') as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, path)
        except Exception as e:
            log.error(f"State save failed: {e}")

    @classmethod
    def load(cls, path: str = "bot_state.json") -> 'BotState':
        """加载状态，文件缺失/损坏返回新实例"""
        try:
            with open(path) as f:
                data = json.load(f)
            state = cls(**{k: v for k, v in data.items()
                          if k in cls.__dataclass_fields__})
            state.check_daily_reset()
            state._state_path = path
            log.info(f"✅ State loaded: PnL=${state.total_pnl:.2f} today=${state.daily_pnl:.2f}")
            return state
        # Catch all errors: OSError (IsADirectoryError for Docker volumes, PermissionError),
        # JSON/type errors from corrupted state, and anything else unexpected.
        except Exception as e:
            log.info(f"No valid state file, starting fresh: {type(e).__name__}: {e}")
            state = cls()
            state.current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            state._state_path = path
            return state
