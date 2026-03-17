import asyncio
from datetime import datetime, timedelta
from lib.polymarket_client import PolymarketClient
from lib.trading_engine import TradingEngine
from lib.data_persistence import DataPersistence

class ProfitOptimizedStrategy:
    """优化盈利的交易策略"""
    
    def __init__(self):
        self.client = PolymarketClient()
        self.engine = TradingEngine(dry_run=False)
        self.db = DataPersistence()
        self.price_history = []
        self.max_history = 100
        
    def calculate_volatility(self):
        """计算价格波动率"""
        if len(self.price_history) < 2:
            return 0
        
        prices = [p['price'] for p in self.price_history]
        avg_price = sum(prices) / len(prices)
        variance = sum((p - avg_price) ** 2 for p in prices) / len(prices)
        volatility = variance ** 0.5
        return volatility / avg_price if avg_price > 0 else 0
    
    def get_price_trend(self):
        """获取价格趋势"""
        if len(self.price_history) < 5:
            return 0
        
        recent = self.price_history[-5:]
        trend = (recent[-1]['price'] - recent[0]['price']) / recent[0]['price']
        return trend
    
    def calculate_optimal_grid(self, current_price, volatility):
        """根据波动率计算最优网格"""
        
        # 高波动率 -> 小步长，多层级
        # 低波动率 -> 大步长，少层级
        
        if volatility > 0.02:
            return {
                'levels': 8,
                'step': 0.005,
                'order_size': 0.5
            }
        elif volatility > 0.01:
            return {
                'levels': 5,
                'step': 0.01,
                'order_size': 1.0
            }
        else:
            return {
                'levels': 3,
                'step': 0.02,
                'order_size': 2.0
            }
    
    def should_buy(self, current_price, trend, volatility):
        """决定是否买入"""
        # 买入条件:
        # 1. 价格在历史低位
        # 2. 向上趋势
        # 3. 足够的波动率
        
        if len(self.price_history) < 10:
            return False
        
        min_price = min(p['price'] for p in self.price_history[-20:])
        max_price = max(p['price'] for p in self.price_history[-20:])
        
        price_percentile = (current_price - min_price) / (max_price - min_price)
        
        return (price_percentile < 0.4 and  # 低于 40% 位置
                trend > 0 and               # 向上趋势
                volatility > 0.005)         # 足够波动
    
    def should_sell(self, current_price, position, entry_price):
        """决定是否卖出"""
        # 卖出条件:
        # 1. 止盈 (2% 利润)
        # 2. 止损 (-1% 亏损)
        
        pnl_pct = (current_price - entry_price) / entry_price
        
        if pnl_pct > 0.02:   # 2% 利润
            return True, "止盈"
        elif pnl_pct < -0.01:  # 1% 亏损
            return True, "止损"
        
        return False, None
    
    async def execute_smart_trades(self, market):
        """执行智能交易"""
        
        # 获取当前价格
        token_id = market.get('id')
        orderbook = self.client.get_orderbook(token_id)
        prices = self.client.calculate_mid_price(orderbook)
        current_price = prices['mid']
        
        # 更新价格历史
        self.price_history.append({
            'price': current_price,
            'timestamp': datetime.now()
        })
        if len(self.price_history) > self.max_history:
            self.price_history.pop(0)
        
        # 计算指标
        volatility = self.calculate_volatility()
        trend = self.get_price_trend()
        
        # 获取最优网格
        grid_config = self.calculate_optimal_grid(current_price, volatility)
        
        # 决定交易
        if self.should_buy(current_price, trend, volatility):
            for i in range(grid_config['levels']):
                buy_price = current_price - (i * grid_config['step'])
                self.engine.place_order(
                    token_id, 'buy', buy_price, grid_config['order_size']
                )
        
        return {
            'current_price': current_price,
            'volatility': volatility,
            'trend': trend,
            'grid': grid_config
        }
