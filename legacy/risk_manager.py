class RiskManager:
    """Advanced risk management for profitability"""
    
    def __init__(self):
        self.daily_pnl = 0
        self.trades_today = 0
        self.win_rate = 0
        self.max_loss_per_trade = 10  # 每笔交易最大损失
        self.daily_loss_limit = 100   # 每天最大损失
        self.min_win_rate = 0.55      # 最小赢率 55%
        
    def should_trade(self, current_pnl, position_size, price_volatility):
        """决定是否下单"""
        
        # 检查 1: 日损失限制
        if self.daily_pnl < -self.daily_loss_limit:
            return False, "已达日损失限制"
        
        # 检查 2: 赢率要求
        if self.trades_today > 10 and self.win_rate < self.min_win_rate:
            return False, "赢率低于最低要求"
        
        # 检查 3: 头寸大小
        if position_size > self.daily_loss_limit / 2:
            return False, "头寸过大"
        
        # 检查 4: 波动率
        if price_volatility < 0.005:
            return False, "波动率过低，不值得交易"
        
        return True, "可以交易"
    
    def update_trade_result(self, pnl, is_win):
        """更新交易结果"""
        self.daily_pnl += pnl
        self.trades_today += 1
        
        if self.trades_today > 0:
            wins = int(self.trades_today * self.win_rate) + (1 if is_win else 0)
            self.win_rate = wins / self.trades_today
        
        return {
            'daily_pnl': self.daily_pnl,
            'trades': self.trades_today,
            'win_rate': self.win_rate
        }
