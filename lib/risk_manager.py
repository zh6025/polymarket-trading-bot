from dataclasses import dataclass, asdict
from datetime import datetime, date
from typing import Optional, Dict, Any

@dataclass
class RiskDecision:
    allowed: bool
    reason: str
    adjusted_size: float
    metadata: Dict[str, Any]


class RiskManager:
    """Risk manager for position sizing and session-level guardrails."""

    def __init__(
        self,
        max_loss_per_trade: float = 10.0,
        daily_loss_limit: float = 100.0,
        min_win_rate: float = 0.55,
        max_position_size: float = 50.0,
        min_volatility: float = 0.005,
        cooldown_after_losses: int = 3,
    ):
        self.max_loss_per_trade = float(max_loss_per_trade)
        self.daily_loss_limit = float(daily_loss_limit)
        self.min_win_rate = float(min_win_rate)
        self.max_position_size = float(max_position_size)
        self.min_volatility = float(min_volatility)
        self.cooldown_after_losses = int(cooldown_after_losses)

        self.current_day = date.today()
        self.daily_pnl = 0.0
        self.trades_today = 0
        self.wins_today = 0
        self.losses_today = 0
        self.consecutive_losses = 0
        self.last_trade_at: Optional[str] = None

    def _reset_if_new_day(self):
        today = date.today()
        if today != self.current_day:
            self.current_day = today
            self.daily_pnl = 0.0
            self.trades_today = 0
            self.wins_today = 0
            self.losses_today = 0
            self.consecutive_losses = 0
            self.last_trade_at = None

    @property
    def win_rate(self) -> float:
        if self.trades_today == 0:
            return 0.0
        return self.wins_today / self.trades_today

    def should_trade(
        self,
        current_pnl: float,
        position_size: float,
        price_volatility: float,
        requested_size: float = 1.0,
        estimated_risk: Optional[float] = None,
        market_spread: Optional[float] = None,
        time_to_expiry_seconds: Optional[float] = None,
    ) -> RiskDecision:
        """Decide whether a trade is allowed and optionally scale its size."""
        self._reset_if_new_day()

        adjusted_size = min(float(requested_size), self.max_position_size)
        metadata: Dict[str, Any] = {
            'current_pnl': float(current_pnl),
            'daily_pnl': self.daily_pnl,
            'position_size': float(position_size),
            'requested_size': float(requested_size),
            'estimated_risk': None if estimated_risk is None else float(estimated_risk),
            'market_spread': None if market_spread is None else float(market_spread),
            'time_to_expiry_seconds': None if time_to_expiry_seconds is None else float(time_to_expiry_seconds),
            'consecutive_losses': self.consecutive_losses,
            'win_rate': self.win_rate,
        }

        if self.daily_pnl <= -self.daily_loss_limit:
            return RiskDecision(False, '已达日损失限制', 0.0, metadata)

        if self.consecutive_losses >= self.cooldown_after_losses:
            return RiskDecision(False, '连续亏损过多，进入冷却', 0.0, metadata)

        if self.trades_today >= 10 and self.win_rate < self.min_win_rate:
            return RiskDecision(False, '赢率低于最低要求', 0.0, metadata)

        if price_volatility < self.min_volatility:
            return RiskDecision(False, '波动率过低，不值得交易', 0.0, metadata)

        if position_size >= self.max_position_size:
            return RiskDecision(False, '头寸已达��限', 0.0, metadata)

        remaining_capacity = max(self.max_position_size - float(position_size), 0.0)
        adjusted_size = min(adjusted_size, remaining_capacity)
        if adjusted_size <= 0:
            return RiskDecision(False, '无剩余可用仓位', 0.0, metadata)

        if estimated_risk is not None and estimated_risk > self.max_loss_per_trade:
            scale = self.max_loss_per_trade / estimated_risk if estimated_risk > 0 else 0.0
            adjusted_size *= scale
            metadata['risk_scale'] = scale
            if adjusted_size <= 0:
                return RiskDecision(False, '单笔风险过高', 0.0, metadata)

        if market_spread is not None and market_spread > 0.03:
            return RiskDecision(False, '点差过大，跳过交易', 0.0, metadata)

        if time_to_expiry_seconds is not None and time_to_expiry_seconds < 30:
            return RiskDecision(False, '距离结算过近，禁止开新仓', 0.0, metadata)

        metadata['approved_size'] = adjusted_size
        return RiskDecision(True, '可以交易', adjusted_size, metadata)

    def update_trade_result(self, pnl: float, is_win: bool) -> Dict[str, Any]:
        """Update trade outcome statistics with correct win/loss accounting."""
        self._reset_if_new_day()

        self.daily_pnl += float(pnl)
        self.trades_today += 1
        self.last_trade_at = datetime.utcnow().isoformat()

        if is_win:
            self.wins_today += 1
            self.consecutive_losses = 0
        else:
            self.losses_today += 1
            self.consecutive_losses += 1

        return self.get_metrics()

    def get_metrics(self) -> Dict[str, Any]:
        self._reset_if_new_day()
        return {
            'current_day': self.current_day.isoformat(),
            'daily_pnl': self.daily_pnl,
            'trades_today': self.trades_today,
            'wins_today': self.wins_today,
            'losses_today': self.losses_today,
            'consecutive_losses': self.consecutive_losses,
            'win_rate': self.win_rate,
            'last_trade_at': self.last_trade_at,
            'limits': {
                'max_loss_per_trade': self.max_loss_per_trade,
                'daily_loss_limit': self.daily_loss_limit,
                'min_win_rate': self.min_win_rate,
                'max_position_size': self.max_position_size,
                'min_volatility': self.min_volatility,
                'cooldown_after_losses': self.cooldown_after_losses,
            },
        }