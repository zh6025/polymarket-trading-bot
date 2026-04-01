from typing import Dict, Any, Optional
from lib.utils import log_warn, log_info

class RiskManager:
    """Risk Management Module"""
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize risk manager with config"""
        self.config = config
        self.daily_loss = 0.0
        self.positions = {}  # outcome -> {size, avg_price, pnl}
        self.circuit_breaker_triggered = False
    
    def check_daily_loss_limit(self, current_pnl: float) -> bool:
        """Check if daily loss limit exceeded"""
        limit = self.config.get('daily_loss_limit', 1000)
        
        if current_pnl < -limit:
            log_warn(f"⛔ Daily loss limit exceeded: {current_pnl} < -{limit}")
            self.circuit_breaker_triggered = True
            return False
        
        return True
    
    def check_position_limit(self, outcome: str, size: float) -> bool:
        """Check if position limit exceeded"""
        limit = self.config.get('max_position_size', 5000)
        
        current_pos = self.positions.get(outcome, {}).get('size', 0)
        
        if current_pos + size > limit:
            log_warn(f"⛔ Position limit exceeded for {outcome}: {current_pos + size} > {limit}")
            return False
        
        return True
    
    def update_position(self, outcome: str, size: float, price: float):
        """Update position after trade"""
        if outcome not in self.positions:
            self.positions[outcome] = {'size': 0, 'avg_price': 0, 'pnl': 0}
        
        pos = self.positions[outcome]
        total_size = pos['size'] + size;
        
        if total_size != 0:
            pos['avg_price'] = (pos['size'] * pos['avg_price'] + size * price) / total_size
            pos['size'] = total_size
        else:
            pos['size'] = 0
            pos['avg_price'] = 0
    
    def calculate_total_pnl(self, current_prices: Dict[str, float]) -> float:
        """Calculate total PnL"""
        total_pnl = 0.0
        
        for outcome, pos in self.positions.items():
            if pos['size'] != 0 and outcome in current_prices:
                pnl = pos['size'] * (current_prices[outcome] - pos['avg_price'])
                total_pnl += pnl
        
        return total_pnl
    
    def get_status(self) -> Dict[str, Any]:
        """Get risk manager status"""
        return {
            'circuit_breaker_triggered': self.circuit_breaker_triggered,
            'positions': self.positions,
            'daily_loss': self.daily_loss
        }