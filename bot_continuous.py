import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List
from lib.polymarket_client import PolymarketClient
from lib.trading_engine import TradingEngine
from lib.data_persistence import DataPersistence
from lib.utils import log_info, log_error, log_warn

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")

class ContinuousGridTrader:
    """连续 5 分钟周期网格交易机器人"""
    
    def __init__(self, dry_run=True):
        self.client = PolymarketClient()
        self.engine = TradingEngine(dry_run=dry_run)
        self.db = DataPersistence()
        self.dry_run = dry_run
        
        # 交易周期配置
        self.cycle_duration = 300  # 5 分钟 = 300 秒
        self.check_interval = 5    # 每 5 秒检查一次市场
        
        # 市场跟踪
        self.market_history = []
        self.current_market = None
        self.market_prices = {}
        
        # 统计数据
        self.total_cycles = 0
        self.daily_pnl = 0
        self.winning_trades = 0
        self.losing_trades = 0
    
    def find_tradable_markets(self) -> List[Dict]:
        """通过 Gamma API 动态查找当前 BTC 5分钟可交易市场"""
        event = self.client.get_current_btc_5m_market()
        if not event:
            return []

        tradable = []
        for m in event.get('markets', []):
            if not m.get('acceptingOrders', False):
                continue
            if m.get('closed', True):
                continue

            import json as _json
            _raw = m.get('clobTokenIds', [])
            clob_token_ids = _json.loads(_raw) if isinstance(_raw, str) else _raw
            if not clob_token_ids or len(clob_token_ids) < 2:
                continue

            tradable.append({
                'question': m.get('question', event.get('title', '')),
                'condition_id': m.get('conditionId', ''),
                'accepting_orders': True,
                'tokens': [
                    {'token_id': clob_token_ids[0], 'outcome': 'UP'},
                    {'token_id': clob_token_ids[1], 'outcome': 'DOWN'},
                ],
                'min_order_size': float(m.get('orderMinSize', 5)),
                'tick_size': float(m.get('orderPriceMinTickSize', 0.01)),
            })

        log_info(f"找到 {len(tradable)} 个 BTC 5分钟可交易市场")
        return tradable
    
    def filter_by_status(self, markets, status='any'):
        """根据状态筛选市场"""
        if status == 'active_only':
            # 严格模式：只要活跃且接受订单
            return [m for m in markets 
                    if m.get('active', False) and 
                       not m.get('closed', True) and 
                       m.get('accepting_orders', False)]
        
        elif status == 'accepting':
            # 宽松模式：接受订单的市场
            return [m for m in markets if m.get('accepting_orders', False)]
        
        elif status == 'active':
            # 宽松模式：活跃的市场
            return [m for m in markets if m.get('active', False)]
        
        else:  # 'any'
            # 最宽松：所有 BTC 市场（用于演示）
            return markets
    
    async def analyze_market(self, market):
        """分析市场数据并生成交易信号"""
        try:
            tokens = market.get('tokens', [])
            if not tokens or len(tokens) < 2:
                return None
            
            results = {}
            
            for token in tokens:
                token_id = token.get('token_id')
                outcome = token.get('outcome', 'Unknown')
                
                try:
                    orderbook = self.client.get_orderbook(token_id)
                    prices = self.client.calculate_mid_price(orderbook)
                    
                    # 保存价格
                    if token_id not in self.market_prices:
                        self.market_prices[token_id] = []
                    
                    self.market_prices[token_id].append({
                        'price': prices['mid'],
                        'bid': prices['bid'],
                        'ask': prices['ask'],
                        'timestamp': datetime.now()
                    })
                    
                    # 只保留最近 20 个数据点
                    if len(self.market_prices[token_id]) > 20:
                        self.market_prices[token_id].pop(0)
                    
                    # 计算指标
                    volatility = self._calculate_volatility(token_id)
                    trend = self._calculate_trend(token_id)
                    
                    results[outcome] = {
                        'token_id': token_id,
                        'price': prices['mid'],
                        'bid': prices['bid'],
                        'ask': prices['ask'],
                        'volatility': volatility,
                        'trend': trend,
                        'signal': self._generate_signal(prices['mid'], volatility, trend)
                    }
                    
                except Exception as e:
                    log_warn(f"分析 {outcome} token 失败: {e}")
                    # 继续下一个 token，不中断整个分析
            
            return results if results else None
        
        except Exception as e:
            log_error(f"市场分析错误: {e}")
            return None
    
    def _calculate_volatility(self, token_id):
        """计算波动率"""
        if token_id not in self.market_prices or len(self.market_prices[token_id]) < 2:
            return 0
        
        prices = [p['price'] for p in self.market_prices[token_id]]
        avg_price = sum(prices) / len(prices)
        variance = sum((p - avg_price) ** 2 for p in prices) / len(prices)
        volatility = variance ** 0.5
        return volatility / avg_price if avg_price > 0 else 0
    
    def _calculate_trend(self, token_id):
        """计算价格趋势"""
        if token_id not in self.market_prices or len(self.market_prices[token_id]) < 5:
            return 0
        
        prices = self.market_prices[token_id]
        trend = (prices[-1]['price'] - prices[0]['price']) / prices[0]['price']
        return trend
    
    def _generate_signal(self, price, volatility, trend):
        """生成交易信号"""
        # 信号等级: STRONG_BUY=2, BUY=1, HOLD=0, SELL=-1, STRONG_SELL=-2
        
        if volatility < 0.0001:
            return 0  # 波动率太低，不交易
        
        if trend > 0.02 and volatility > 0.001:
            return 2  # 强买信号
        elif trend > 0.01 and volatility > 0.0005:
            return 1  # 买信号
        elif trend < -0.02 and volatility > 0.001:
            return -2  # 强卖信号
        elif trend < -0.01 and volatility > 0.0005:
            return -1  # 卖信号
        
        return 0  # 持有
    
    async def execute_grid_trades(self, market, analysis):
        """执行网格交易"""
        try:
            if not analysis:
                return None
            
            market_question = market.get('question', 'Unknown')
            trades_executed = []
            
            for outcome, data in analysis.items():
                token_id = data['token_id']
                signal = data['signal']
                price = data['price']
                
                # 根据信号决定是否交易
                if signal > 0:  # 买信号
                    grid_levels = abs(signal)
                    grid_step = 0.01
                    order_size = 1.0
                    
                    for i in range(grid_levels):
                        buy_price = price - (i * grid_step)
                        if buy_price > 0.01:
                            order_id = self.engine.place_order(
                                token_id, 'buy', buy_price, order_size
                            )
                            
                            # 保存到数据库
                            self.db.save_trade({
                                'order_id': order_id,
                                'token_id': token_id,
                                'side': 'buy',
                                'price': buy_price,
                                'size': order_size,
                                'timestamp': datetime.now().isoformat()
                            })
                            
                            trades_executed.append({
                                'outcome': outcome,
                                'side': 'buy',
                                'price': buy_price,
                                'size': order_size
                            })
                
                elif signal < 0:  # 卖信号
                    grid_levels = abs(signal)
                    grid_step = 0.01
                    order_size = 1.0
                    
                    for i in range(grid_levels):
                        sell_price = price + (i * grid_step)
                        if sell_price < 0.99:
                            order_id = self.engine.place_order(
                                token_id, 'sell', sell_price, order_size
                            )
                            
                            self.db.save_trade({
                                'order_id': order_id,
                                'token_id': token_id,
                                'side': 'sell',
                                'price': sell_price,
                                'size': order_size,
                                'timestamp': datetime.now().isoformat()
                            })
                            
                            trades_executed.append({
                                'outcome': outcome,
                                'side': 'sell',
                                'price': sell_price,
                                'size': order_size
                            })
            
            return trades_executed
        
        except Exception as e:
            log_error(f"执行交易失败: {e}")
            return []
    
    async def run_cycle(self):
        """运行一个 5 分钟交易周期"""
        self.total_cycles += 1
        cycle_start = datetime.now()
        
        print("\n" + "="*80)
        print(f"🔄 交易周期 #{self.total_cycles} - {cycle_start.strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*80)
        
        try:
            # 找到可交易的市场
            tradable = self.find_tradable_markets()
            log_info(f"找到 {len(tradable)} 个 BTC 可交易市场")
            
            if not tradable:
                log_warn("未找到任何 BTC 可交易市场")
                return
            
            # 优先尝试活跃且接受订单的市场
            active_only = self.filter_by_status(tradable, 'active_only')
            if active_only:
                markets_to_trade = active_only
                print(f"✅ 找到 {len(active_only)} 个活跃市场（正在接受订单）")
            else:
                # 次选：只要接受订单的
                accepting = self.filter_by_status(tradable, 'accepting')
                if accepting:
                    markets_to_trade = accepting
                    print(f"⚠️  找到 {len(accepting)} 个接受订单的市场")
                else:
                    # 最后选择：所有 BTC 市场（演示模式）
                    markets_to_trade = self.filter_by_status(tradable, 'any')[:5]
                    print(f"📌 演示模式：显示前 {len(markets_to_trade)} 个 BTC 市场")
            
            # 遍历所有活跃市场
            trades_total = 0
            for idx, market in enumerate(markets_to_trade, 1):
                market_question = market.get('question', 'Unknown')[:70]
                market_slug = market.get('market_slug', 'N/A')
                
                print(f"\n📊 市场 {idx}/{len(markets_to_trade)}: {market_question}")
                print(f"   Slug: {market_slug}")
                print(f"   状态: 活跃={market.get('active')}, 已关闭={market.get('closed')}, 接受订单={market.get('accepting_orders')}")
                
                # 分析市场
                analysis = await self.analyze_market(market)
                
                if analysis:
                    print("\n   📈 市场分析结果:")
                    for outcome, data in analysis.items():
                        signal_text = {
                            2: "🟢🟢 强买",
                            1: "🟢 买",
                            0: "⚪ 持有",
                            -1: "🔴 卖",
                            -2: "🔴🔴 强卖"
                        }.get(data['signal'], "❓ 未知")
                        
                        print(f"     {outcome}:")
                        print(f"       💰 价格: {data['price']:.4f}")
                        print(f"       📊 BID/ASK: {data['bid']:.4f} / {data['ask']:.4f}")
                        print(f"       📈 波动率: {data['volatility']:.6f}")
                        print(f"       📉 趋势: {data['trend']:+.6f}")
                        print(f"       🎯 信号: {signal_text}")
                    
                    # 执行交易
                    trades = await self.execute_grid_trades(market, analysis)
                    
                    if trades:
                        print(f"\n   ✅ 执行了 {len(trades)} 笔交易")
                        trades_total += len(trades)
                        for trade in trades[:3]:  # 只显示前 3 笔
                            print(f"     • {trade['outcome']} {trade['side'].upper()} @ {trade['price']:.4f}")
                        if len(trades) > 3:
                            print(f"     ... 还有 {len(trades) - 3} 笔交易")
                else:
                    print("   ⚠️  无法分析此市场")
            
            # 显示周期统计
            stats = self.engine.get_statistics()
            print(f"\n📊 周期统计:")
            print(f"   本周期交易: {trades_total}")
            print(f"   总订单: {stats['total_orders']}")
            print(f"   成交: {stats['filled_orders']}")
            print(f"   未实现PnL: {stats['unrealized_pnl']:.4f}")
            
        except Exception as e:
            log_error(f"周期执行失败: {e}")
            import traceback
            traceback.print_exc()
    
    async def continuous_trading_loop(self):
        """连续交易主循环"""
        print("""
╔══════════════════════════════════════════════════════════════════════╗
║           Polymarket - 连续 5 分钟网格交易机器人                     ║
║                   🎯 目标: 持续自动盈利                              ║
╚══════════════════════════════════════════════════════════════════════╝
        """)
        
        if self.dry_run:
            print("⚠️  运行模式: 干运行（模拟交易）")
        else:
            print("🔴 运行模式: 真实交易（注意风险！）")
        
        print(f"⏰ 周期时长: {self.cycle_duration} 秒")
        print(f"📊 检查间隔: {self.check_interval} 秒\n")
        
        while True:
            try:
                cycle_start = datetime.now()
                
                # 运行一个交易周期
                await self.run_cycle()
                
                # 计算本周期耗时
                elapsed = (datetime.now() - cycle_start).total_seconds()
                wait_time = max(self.cycle_duration - elapsed, self.check_interval)
                
                print(f"\n⏳ 本周期耗时: {elapsed:.1f}秒，等待 {wait_time:.1f}秒...")
                print("="*80)
                
                # 等待下个周期
                await asyncio.sleep(wait_time)
                
            except KeyboardInterrupt:
                self.shutdown()
                break
            except Exception as e:
                log_error(f"主循环错误: {e}")
                await asyncio.sleep(10)
    
    def shutdown(self):
        """关闭机器人"""
        print("\n" + "="*80)
        print("🛑 机器人关闭")
        print("="*80)
        
        stats = self.engine.get_statistics()
        performance = self.db.get_performance_summary(hours=24)
        
        print(f"""
📊 最终统计:
   总周期: {self.total_cycles}
   总订单: {stats['total_orders']}
   成交: {stats['filled_orders']}
   总交易: {stats['total_trades']}
   未实现PnL: {stats['unrealized_pnl']:.4f}
   
📈 性能指标 (24小时):
   平均PnL: {performance.get('avg_pnl', 0):.4f}
   最高PnL: {performance.get('max_pnl', 0):.4f}
   最低PnL: {performance.get('min_pnl', 0):.4f}
        """)
        
        self.db.close()


async def main():
    """主入口"""
    import os
    from lib.config import Config
    
    config = Config()
    
    # 创建交易机器人
    bot = ContinuousGridTrader(dry_run=config.dry_run)
    
    # 运行连续交易
    await bot.continuous_trading_loop()


if __name__ == "__main__":
    asyncio.run(main())
