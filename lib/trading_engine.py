import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from lib.utils import log_info, log_error, log_warn

logger = logging.getLogger(__name__)

class TradingEngine:
    """Real-time trading execution engine with order management"""
    
    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run
        self.orders: Dict[str, Dict] = {}
        self.positions: Dict[str, float] = {}
        self.trades: List[Dict] = []
        self.pnl: float = 0.0
        self.order_counter = 0
    
    def place_order(self, token_id: str, side: str, price: float, size: float) -> str:
        """Place buy/sell order"""
        self.order_counter += 1
        order_id = f"order_{self.order_counter}_{datetime.now().timestamp()}"
        
        order = {
            'id': order_id,
            'token_id': token_id,
            'side': side,
            'price': price,
            'size': size,
            'status': 'pending' if not self.dry_run else 'filled',
            'timestamp': datetime.now().isoformat(),
            'filled_size': 0,
            'avg_price': 0
        }
        
        self.orders[order_id] = order
        
        if self.dry_run:
            self._fill_order(order_id)
        
        log_info(f"Order placed: {side.upper()} {size:.2f} @ {price:.4f}")
        return order_id
    
    def _fill_order(self, order_id: str):
        """Simulate order fill"""
        order = self.orders.get(order_id)
        if not order:
            return
        
        order['status'] = 'filled'
        order['filled_size'] = order['size']
        order['avg_price'] = order['price']
        
        token_id = order['token_id']
        current_pos = self.positions.get(token_id, 0)
        
        if order['side'] == 'buy':
            self.positions[token_id] = current_pos + order['size']
        else:
            self.positions[token_id] = current_pos - order['size']
        
        self.trades.append({
            'order_id': order_id,
            'token_id': token_id,
            'side': order['side'],
            'price': order['price'],
            'size': order['size'],
            'timestamp': order['timestamp']
        })
        
        log_info(f"Order filled: {order_id}")
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get trading statistics"""
        filled_orders = [o for o in self.orders.values() if o['status'] == 'filled']
        
        return {
            'total_orders': len(self.orders),
            'filled_orders': len(filled_orders),
            'total_trades': len(self.trades),
            'positions': self.positions,
            'unrealized_pnl': self.pnl,
            'dry_run': self.dry_run
        }
