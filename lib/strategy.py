from typing import List, Dict, Any, Tuple
from lib.utils import round_to_tick, log_info
from lib.directional_strategy import DirectionalStrategy
from lib.momentum_hedge_strategy import MomentumHedgeStrategy

__all__ = ["GridStrategy", "DirectionalStrategy", "MomentumHedgeStrategy"]

class GridStrategy:
    """Grid Trading Strategy"""
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize grid strategy with config"""
        self.config = config
        self.grid_levels = []
        self.orders = []
    
    def validate_config(self, tick_size: float, min_order_size: float):
        """Validate strategy configuration"""
        order_size = self.config.get('order_size', 5)
        grid_step = self.config.get('grid_step', 0.02)
        
        if order_size < min_order_size:
            raise ValueError(f"order_size ({order_size}) < min_order_size ({min_order_size})")
        
        # Check if grid_step is multiple of tick_size
        steps_in_ticks = round(grid_step / tick_size)
        step_in_ticks = steps_in_ticks * tick_size
        
        if abs(step_in_ticks - grid_step) > 1e-10:
            raise ValueError(f"grid_step ({grid_step}) is not multiple of tick_size ({tick_size})")
        
        log_info("✅ Strategy config validated")
    
    def generate_grid_levels(
        self,
        mid_price: float,
        tick_size: float,
        grid_step: float,
        levels_each_side: int
    ) -> List[float]:
        """Generate grid price levels"""
        levels = []
        
        # Lower levels
        for i in range(levels_each_side, 0, -1):
            price = round_to_tick(mid_price - grid_step * i, tick_size)
            if tick_size <= price <= 1 - tick_size:
                levels.append(price)
        
        # Center level
        levels.append(round_to_tick(mid_price, tick_size))
        
        # Upper levels
        for i in range(1, levels_each_side + 1):
            price = round_to_tick(mid_price + grid_step * i, tick_size)
            if tick_size <= price <= 1 - tick_size:
                levels.append(price)
        
        self.grid_levels = levels
        log_info(f"✅ Generated {len(levels)} grid levels")
        return levels
    
    def generate_order_plan(
        self,
        up_mid: float,
        down_mid: float,
        up_token: str,
        down_token: str,
        trade_both: bool = True
    ) -> List[Dict[str, Any]]:
        """Generate order plan based on grid levels"""
        plan = []
        order_size = self.config.get('order_size', 5)
        
        # Up side orders
        for price in self.grid_levels:
            if price < up_mid:
                plan.append({
                    'side': 'BUY',
                    'outcome': 'Up',
                    'token_id': up_token,
                    'price': price,
                    'size': order_size
                })
            elif price > up_mid:
                plan.append({
                    'side': 'SELL',
                    'outcome': 'Up',
                    'token_id': up_token,
                    'price': price,
                    'size': order_size
                })
        
        # Down side orders
        if trade_both:
            for price in self.grid_levels:
                if price < down_mid:
                    plan.append({
                        'side': 'BUY',
                        'outcome': 'Down',
                        'token_id': down_token,
                        'price': price,
                        'size': order_size
                    })
                elif price > down_mid:
                    plan.append({
                        'side': 'SELL',
                        'outcome': 'Down',
                        'token_id': down_token,
                        'price': price,
                        'size': order_size
                    })
        
        self.orders = plan
        log_info(f"✅ Generated {len(plan)} orders")
        return plan
    
    def get_order_plan(self) -> List[Dict[str, Any]]:
        """Get sorted order plan"""
        return sorted(
            self.orders,
            key=lambda o: (o['outcome'], o['price'])
        )
