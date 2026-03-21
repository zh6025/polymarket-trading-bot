import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List
from lib.polymarket_client import PolymarketClient
from lib.trading_engine import TradingEngine
from lib.data_persistence import DataPersistence
from lib.utils import log_info, log_error, log_warn

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")

class ContinuousGridTrader:
    """连续 5 分钟周期网格交易机器人"""
    
    def __init__(self, dry_run=True, strategy='grid', strategy_config=None):
        self.client = PolymarketClient()
        self.engine = TradingEngine(dry_run=dry_run)
        self.db = DataPersistence()
        self.dry_run = dry_run
        self.strategy_name = strategy
        
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

        # 动量对冲策略 / Momentum hedge strategy
        if strategy == 'momentum_hedge':
            from lib.momentum_hedge_strategy import MomentumHedgeStrategy
            cfg = strategy_config or {}
            self.momentum_strategy = MomentumHedgeStrategy(cfg)
        else:
            self.momentum_strategy = None
    
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
        if self.strategy_name == 'momentum_hedge':
            await self._momentum_hedge_loop()
        else:
            await self._grid_trading_loop()

    async def _momentum_hedge_loop(self):
        """
        动量对冲策略主循环
        Momentum hedge strategy main loop — checks every 10 seconds.
        """
        print("""
╔══════════════════════════════════════════════════════════════════════╗
║       Polymarket - 动量对冲策略机器人 (Momentum Hedge Bot)           ║
║          🎯 70/30 触发 + Kelly 最优对冲 | Kelly-Optimal Hedge         ║
╚══════════════════════════════════════════════════════════════════════╝
        """)

        if self.dry_run:
            print("⚠️  运行模式: 干运行（模拟交易）| DRY RUN (simulated trades)")
        else:
            print("🔴 运行模式: 真实交易（注意风险！）| LIVE TRADING (real funds!)")

        cfg = self.momentum_strategy.config
        print(f"📊 触发阈值 Threshold : {cfg.get('trigger_threshold', 0.70):.0%}")
        print(f"💰 总投注额 Bet size  : {cfg.get('total_bet_size', 4.0)} USDC")
        print(f"⏱  最少剩余 Min secs  : {cfg.get('min_remaining_seconds', 60):.0f}s")
        print(f"🔝 最高价格 Max price : {cfg.get('max_trigger_price', 0.85):.0%}")
        print(f"🧮 动态对冲 Dynamic r : {cfg.get('use_dynamic_ratio', True)}\n")

        # Track last day reset
        last_reset_day = datetime.now(timezone.utc).date()

        while True:
            try:
                # Daily state reset 每日重置
                today = datetime.now(timezone.utc).date()
                if today != last_reset_day:
                    self.momentum_strategy.reset_for_new_day()
                    last_reset_day = today

                await self._run_momentum_hedge_check()

                # 每 10 秒检查一次 / Check every 10 seconds
                await asyncio.sleep(10)

            except KeyboardInterrupt:
                self.shutdown()
                break
            except Exception as e:
                log_error(f"动量对冲主循环错误 | Momentum hedge loop error: {e}")
                await asyncio.sleep(10)

    async def _run_momentum_hedge_check(self):
        """
        单次动量对冲检查
        Run a single momentum-hedge market check cycle.
        """
        # 获取当前活跃市场 / Get current active market
        event = self.client.get_current_btc_5m_market()
        if not event:
            log_warn("⚠️  未找到活跃的BTC 5分钟市场 | No active BTC 5m market found")
            return

        markets = event.get('markets', [])
        active = [
            m for m in markets
            if m.get('acceptingOrders', False) and not m.get('closed', True)
        ]
        if not active:
            log_warn("⚠️  当前无接受订单的市场 | No market currently accepting orders")
            return

        market = active[0]

        # 提取 token IDs / Extract token IDs
        _raw = market.get('clobTokenIds', [])
        try:
            clob_token_ids = json.loads(_raw) if isinstance(_raw, str) else _raw
        except (json.JSONDecodeError, TypeError) as exc:
            log_error(f"无法解析市场 token IDs | Failed to parse clobTokenIds: {exc!r}")
            return
        if not clob_token_ids or len(clob_token_ids) < 2:
            log_warn("⚠️  市场 token IDs 不完整 | Incomplete market token IDs")
            return

        up_token_id = clob_token_ids[0]
        down_token_id = clob_token_ids[1]
        market_id = market.get('conditionId', '')

        # 计算剩余时间 / Calculate remaining market time
        end_date_str = market.get('endDateIso') or event.get('endDate', '')
        remaining_seconds = self._calc_remaining_seconds(end_date_str)

        # 获取订单簿 / Get orderbooks
        try:
            up_book = self.client.get_orderbook(up_token_id)
            down_book = self.client.get_orderbook(down_token_id)
        except Exception as e:
            log_error(f"获取订单簿失败 | Failed to fetch orderbooks: {e}")
            return

        up_prices = self.client.calculate_mid_price(up_book)
        down_prices = self.client.calculate_mid_price(down_book)

        up_ask = up_prices['ask']
        down_ask = down_prices['ask']

        log_info(
            f"📊 UP ask: {up_ask:.4f}  DOWN ask: {down_ask:.4f}  "
            f"剩余 remaining: {remaining_seconds:.0f}s  市场 market: {market_id[:8]}…"
        )

        # 生成订单 / Generate orders
        orders = self.momentum_strategy.generate_orders(
            up_ask, down_ask,
            up_token_id, down_token_id,
            market_id,
            remaining_seconds,
        )

        if not orders:
            return

        # 执行订单 / Execute orders
        for order in orders:
            token_id = order['token_id']
            price = order['price']
            size = order['size']
            role = order.get('role', 'main')
            outcome = order['outcome']

            order_id = self.engine.place_order(token_id, 'buy', price, size)

            self.db.save_trade({
                'order_id': order_id,
                'token_id': token_id,
                'side': 'buy',
                'price': price,
                'size': size,
                'timestamp': datetime.now().isoformat(),
                'strategy': 'momentum_hedge',
                'role': role,
                'market_id': market_id,
                'outcome': outcome,
            })

            usdc_spent = size * price
            log_info(
                f"{'✅' if role == 'main' else '🛡️'} 下注 {role.upper()} [{outcome}]: "
                f"{size:.4f} shares @ {price:.4f} (≈{usdc_spent:.2f} USDC)"
                f" | {'main bet' if role == 'main' else 'hedge bet'}"
            )

        # 记录预期盈亏 / Log expected P&L
        trigger = self.momentum_strategy.check_trigger(up_ask, down_ask)
        if trigger:
            total_bet = float(self.momentum_strategy.config.get('total_bet_size', 4.0))
            hedge_ratio = orders[0].get('hedge_ratio', 0.33)
            pnl = self.momentum_strategy.get_expected_pnl(
                trigger['favorite_price'], hedge_ratio, total_bet
            )
            log_info(
                f"📈 预期盈亏 Expected P&L:\n"
                f"   胜 Win  : +{pnl['win_profit']:.4f} USDC\n"
                f"   负 Lose :  {pnl['lose_loss']:.4f} USDC\n"
                f"   期望值 EV:  {pnl['expected_value']:.4f} USDC\n"
                f"   Kelly增长率 growth: {pnl['kelly_growth_rate']:.6f}"
            )

    def _calc_remaining_seconds(self, end_date_str: str) -> float:
        """
        计算市场剩余秒数
        Calculate remaining seconds until market ends from an ISO date string.
        Returns a large value if the end time cannot be parsed.
        """
        if not end_date_str:
            return 999.0
        try:
            end_dt = datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            remaining = (end_dt - now).total_seconds()
            return max(remaining, 0.0)
        except Exception:
            return 999.0

    async def _grid_trading_loop(self):
        """原网格交易主循环 / Original grid trading main loop"""
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

    # 构建策略配置 / Build strategy config
    strategy_config = {
        'trigger_threshold': config.trigger_threshold,
        'total_bet_size': config.total_bet_size,
        'min_remaining_seconds': config.min_remaining_seconds,
        'max_trigger_price': config.max_trigger_price,
        'use_dynamic_ratio': config.use_dynamic_ratio,
        'fixed_hedge_ratio': config.fixed_hedge_ratio,
        'win_rate_slope': config.win_rate_slope,
    }

    # 创建交易机器人
    bot = ContinuousGridTrader(
        dry_run=config.dry_run,
        strategy=config.strategy,
        strategy_config=strategy_config,
    )
    
    # 运行连续交易
    await bot.continuous_trading_loop()


if __name__ == "__main__":
    asyncio.run(main())
