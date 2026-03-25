import asyncio
import logging
from datetime import datetime
from lib.config import Config
from lib.polymarket_client import PolymarketClient
from lib.trading_engine import TradingEngine
from lib.data_persistence import DataPersistence
from lib.utils import log_info, log_error

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")

_config = Config()


class ProfitOptimizedStrategy:
    """优化盈利的交易策略"""

    def __init__(self):
        self.client = PolymarketClient(
            host=_config.host,
            chain_id=_config.chain_id,
            private_key=_config.private_key,
            proxy_address=_config.proxy_address,
        )
        self.engine = TradingEngine(dry_run=True)
        self.db = DataPersistence(db_path="simulate_data.db")
        self.price_history = {}
        self.max_history = 100
    
    def find_active_market(self, markets):
        """找到活跃的、接受订单的市场"""
        active_markets = []
        
        for market in markets:
            # 检查市场是否活跃
            is_active = (
                market.get('active', False) and 
                not market.get('closed', True) and
                market.get('accepting_orders', False)
            )
            
            if is_active:
                question = market.get('question', '').upper()
                # 查找 5分钟 BTC UP/DOWN 市场
                if ('5' in question or '5M' in question or '5分钟' in question) and \
                   ('BTC' in question or 'BITCOIN' in question) and \
                   ('UP' in question or 'DOWN' in question or 'UPS' in question or '上升' in question or '下降' in question):
                    active_markets.append(market)
        
        if active_markets:
            log_info(f"找到 {len(active_markets)} 个活跃的 BTC 5分钟市场")
            return active_markets[0]
        
        # 如果没有找到 5分钟市场，找任何活跃的 BTC 市场
        btc_active = [m for m in markets if 
                      m.get('active', False) and 
                      not m.get('closed', True) and
                      m.get('accepting_orders', False) and
                      ('BTC' in m.get('question', '').upper() or 'BITCOIN' in m.get('question', '').upper())]
        
        if btc_active:
            log_info(f"找到 {len(btc_active)} 个活跃的 BTC 市场")
            return btc_active[0]
        
        return None
    
    def calculate_volatility(self, token_id):
        """计算价格波动率"""
        if token_id not in self.price_history or len(self.price_history[token_id]) < 2:
            return 0
        
        prices = [p['price'] for p in self.price_history[token_id]]
        avg_price = sum(prices) / len(prices)
        variance = sum((p - avg_price) ** 2 for p in prices) / len(prices)
        volatility = variance ** 0.5
        return volatility / avg_price if avg_price > 0 else 0
    
    def get_price_trend(self, token_id):
        """获取价格趋势"""
        if token_id not in self.price_history or len(self.price_history[token_id]) < 5:
            return 0
        
        recent = self.price_history[token_id][-5:]
        trend = (recent[-1]['price'] - recent[0]['price']) / recent[0]['price']
        return trend
    
    async def execute_smart_trades(self):
        """执行智能交易"""
        
        try:
            # 获取市场列表
            markets = self.client.get_markets()
            
            # 查找活跃的市场
            market = self.find_active_market(markets)
            
            if not market:
                log_error("未找到活跃的 BTC 市场")
                # 打印前几个市场的信息用于调试
                for i, m in enumerate(markets[:3]):
                    print(f"\n市场 #{i+1}:")
                    print(f"  问题: {m.get('question', 'N/A')}")
                    print(f"  活跃: {m.get('active', False)}")
                    print(f"  已关闭: {m.get('closed', False)}")
                    print(f"  接受订单: {m.get('accepting_orders', False)}")
                return None
            
            log_info(f"✅ 选择市场: {market.get('question')[:60]}...")
            
            # 从 tokens 数组中提取 token_id
            tokens = market.get('tokens', [])
            if not tokens or len(tokens) == 0:
                log_error("市场中没有 tokens")
                return None
            
            # 获取两个结果的 token
            yes_token = tokens[0]  # "Yes" 结果
            no_token = tokens[1] if len(tokens) > 1 else None  # "No" 结果
            
            results = []
            
            # 获取 YES token 的订单簿
            yes_token_id = yes_token.get('token_id')
            if yes_token_id:
                try:
                    orderbook = self.client.get_orderbook(yes_token_id)
                    prices = self.client.calculate_mid_price(orderbook)
                    
                    # 初始化价格历史
                    if yes_token_id not in self.price_history:
                        self.price_history[yes_token_id] = []
                    
                    self.price_history[yes_token_id].append({
                        'price': prices['mid'],
                        'timestamp': datetime.now()
                    })
                    
                    if len(self.price_history[yes_token_id]) > self.max_history:
                        self.price_history[yes_token_id].pop(0)
                    
                    volatility = self.calculate_volatility(yes_token_id)
                    trend = self.get_price_trend(yes_token_id)
                    
                    results.append({
                        'outcome': yes_token.get('outcome', 'YES'),
                        'token_id': yes_token_id,
                        'price': prices['mid'],
                        'bid': prices['bid'],
                        'ask': prices['ask'],
                        'volatility': volatility,
                        'trend': trend
                    })
                except Exception as e:
                    log_error(f"获取 YES token 数据失败: {e}")
            
            # 获取 NO token 的订单簿
            if no_token:
                no_token_id = no_token.get('token_id')
                if no_token_id:
                    try:
                        orderbook = self.client.get_orderbook(no_token_id)
                        prices = self.client.calculate_mid_price(orderbook)
                        
                        if no_token_id not in self.price_history:
                            self.price_history[no_token_id] = []
                        
                        self.price_history[no_token_id].append({
                            'price': prices['mid'],
                            'timestamp': datetime.now()
                        })
                        
                        if len(self.price_history[no_token_id]) > self.max_history:
                            self.price_history[no_token_id].pop(0)
                        
                        volatility = self.calculate_volatility(no_token_id)
                        trend = self.get_price_trend(no_token_id)
                        
                        results.append({
                            'outcome': no_token.get('outcome', 'NO'),
                            'token_id': no_token_id,
                            'price': prices['mid'],
                            'bid': prices['bid'],
                            'ask': prices['ask'],
                            'volatility': volatility,
                            'trend': trend
                        })
                    except Exception as e:
                        log_error(f"获取 NO token 数据失败: {e}")
            
            if not results:
                log_error("无法获取任何 token 数据")
                return None
            
            return {
                'market': market.get('question', 'Unknown'),
                'market_slug': market.get('market_slug', ''),
                'tokens': results,
                'closed': market.get('closed', False),
                'accepting_orders': market.get('accepting_orders', False)
            }
            
        except Exception as e:
            log_error(f"执行交易出错: {e}")
            import traceback
            traceback.print_exc()
            return None


async def run_simulation():
    """运行模拟交易"""
    
    strategy = ProfitOptimizedStrategy()
    
    print("""
╔═══════════════════════════════════════════════╗
║  Polymarket - 实时交易模拟系统               ║
║  🎯 目标: 测试并优化交易策略                  ║
╚═══════════════════════════════════════════════╝
    """)
    
    cycle = 0
    
    while True:
        try:
            cycle += 1
            log_info(f"📊 交易周期 #{cycle}")
            
            # 执行智能交易
            result = await strategy.execute_smart_trades()
            
            if result:
                print("\n" + "="*70)
                print(f"📈 市场: {result['market'][:70]}")
                print(f"🔗 Slug: {result['market_slug']}")
                print(f"🔒 已关闭: {result['closed']} | 接受订单: {result['accepting_orders']}")
                print("-"*70)
                
                for token_data in result['tokens']:
                    print(f"\n{token_data['outcome']}")
                    print(f"  💰 价格: {token_data['price']:.4f}")
                    print(f"  📊 BID: {token_data['bid']:.4f} | ASK: {token_data['ask']:.4f}")
                    print(f"  📈 波动率: {token_data['volatility']:.6f}")
                    print(f"  📉 趋势: {token_data['trend']:+.6f}")
                
                print("="*70 + "\n")
                
                # 显示交易统计
                stats = strategy.engine.get_statistics()
                print(f"📊 交易统计:")
                print(f"   总订单: {stats['total_orders']}")
                print(f"   成交: {stats['filled_orders']}")
                print(f"   未实现PnL: {stats['unrealized_pnl']:.4f}")
                print()
            else:
                log_error("无法获取有效的市场数据")
            
            # 每 10 秒检查一次
            await asyncio.sleep(10)
            
        except KeyboardInterrupt:
            log_info("🛑 停止交易")
            print("\n" + "="*70)
            print("📊 最终统计")
            print("="*70)
            stats = strategy.engine.get_statistics()
            print(f"总订单数: {stats['total_orders']}")
            print(f"成交订单: {stats['filled_orders']}")
            print(f"总交易数: {stats['total_trades']}")
            print(f"未实现PnL: {stats['unrealized_pnl']:.4f}")
            print("="*70)
            break
        except Exception as e:
            log_error(f"❌ 错误: {e}")
            await asyncio.sleep(10)

if __name__ == "__main__":
    asyncio.run(run_simulation())
