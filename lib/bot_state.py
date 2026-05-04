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
class OpenPosition:
    """已下单但未结算的持仓快照。"""
    order_id: str
    token_id: str
    direction: str            # 'UP' | 'DOWN'
    entry_price: float
    size: float               # 提交订单时的 size
    filled_size: float = 0.0  # 实际成交 size
    avg_fill_price: float = 0.0
    window_open_ts: int = 0
    window_end_ts: int = 0
    market_slug: str = ""
    submitted_at: float = 0.0
    cancelled: bool = False
    settled: bool = False
    pnl: float = 0.0


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
    last_entered_window_ts: int = 0  # 持久化，避免重启后重复入场

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

    def record_open_position(
        self,
        order_id: str,
        token_id: str,
        direction: str,
        entry_price: float,
        size: float,
        window_open_ts: int,
        window_end_ts: int,
        market_slug: str = "",
    ) -> dict:
        """记录一笔已提交但未结算的持仓，写入 open_positions。"""
        pos = asdict(OpenPosition(
            order_id=order_id,
            token_id=token_id,
            direction=direction,
            entry_price=float(entry_price),
            size=float(size),
            window_open_ts=int(window_open_ts),
            window_end_ts=int(window_end_ts),
            market_slug=market_slug,
            submitted_at=time.time(),
        ))
        self.open_positions.append(pos)
        return pos

    def find_open_position(self, order_id: str) -> Optional[dict]:
        for p in self.open_positions:
            if p.get('order_id') == order_id:
                return p
        return None

    def update_open_position(self, order_id: str, **fields) -> Optional[dict]:
        pos = self.find_open_position(order_id)
        if pos is None:
            return None
        pos.update(fields)
        return pos

    def settle_position(self, order_id: str, pnl: float, won: bool) -> Optional[dict]:
        """把 open_positions 中的某条标记为已结算并移到 closed_positions，
        同时调用 record_trade(pnl) 更新风控计数。"""
        pos = self.find_open_position(order_id)
        if pos is None:
            return None
        pos['settled'] = True
        pos['pnl'] = float(pnl)
        pos['won'] = bool(won)
        self.open_positions = [p for p in self.open_positions if p.get('order_id') != order_id]
        self.closed_positions.append(pos)
        self.record_trade(pnl=float(pnl))
        return pos

    def save(self, path: str = "bot_state.json"):
        """原子写入"""
        tmp = path + ".tmp"
        try:
            with open(tmp, 'w') as f:
                json.dump(asdict(self), f, indent=2)
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
            log.info(f"✅ State loaded: PnL=${state.total_pnl:.2f} today=${state.daily_pnl:.2f}")
            return state
        except (FileNotFoundError, json.JSONDecodeError, TypeError) as e:
            log.info(f"No valid state file, starting fresh: {e}")
            state = cls()
            state.current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            return state
