import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from lib.polymarket_client import PolymarketClient
from lib.trading_engine import TradingEngine
from lib.data_persistence import DataPersistence
from lib.directional_strategy import DirectionalStrategy
from lib.utils import log_info, log_error, log_warn

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")

class ContinuousGridTrader:
    """
    连续 5 分钟周期方向性投注机器人。
    Continuous directional betting bot for 5-minute BTC Up/Down binary markets.

    策略核心 / Strategy core:
    - 使用 Binance BTC/USDT 实时 K 线（EMA + ATR）生成方向信号
    - 每个市场只投一边（UP 或 DOWN），绝不同时做双边
    - 只在市场开放早期（前 120 秒）入场
    - 只在赔率有利（ask < max_entry_price）时下注
    """

    def __init__(self, dry_run=True, config_dict: Optional[Dict] = None):
        self.client = PolymarketClient()
        self.engine = TradingEngine(dry_run=dry_run)
        self.db = DataPersistence()
        self.dry_run = dry_run

        cfg = config_dict or {}

        # 使用方向性策略替代网格策略 / Use directional strategy instead of grid
        self.strategy = DirectionalStrategy(cfg)

        # 缩短周期以便尽早捕捉新市场 / Shorter cycle to catch new markets early
        self.cycle_duration = 30   # 30 秒检查一次 / Check every 30 seconds
        self.check_interval = 5    # 每 5 秒检查一次市场 / Market check interval

        # 每个市场只下注一次（记录已投注的市场）/ Track markets already bet on
        self.bet_markets: set = set()

        # 市场跟踪 / Market tracking
        self.market_history = []
        self.current_market = None

        # 统计数据 / Statistics
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
        """
        分析市场数据并生成方向性交易信号。
        Analyze market data and generate a directional betting signal using BTC price.
        """
        try:
            tokens = market.get('tokens', [])
            if not tokens or len(tokens) < 2:
                return None

            # 找到 UP 和 DOWN token / Find UP and DOWN tokens
            up_token = next((t for t in tokens if t.get('outcome', '').upper() == 'UP'), None)
            down_token = next((t for t in tokens if t.get('outcome', '').upper() == 'DOWN'), None)

            if not up_token or not down_token:
                log_warn("⚠️  未找到 UP/DOWN token，跳过此市场")
                return None

            # 获取当前订单簿价格 / Get current orderbook prices
            results = {}
            for token in [up_token, down_token]:
                token_id = token.get('token_id')
                outcome = token.get('outcome', 'Unknown').upper()
                try:
                    orderbook = self.client.get_orderbook(token_id)
                    prices = self.client.calculate_mid_price(orderbook)
                    results[outcome] = {
                        'token_id': token_id,
                        'price': prices['mid'],
                        'bid': prices['bid'],
                        'ask': prices['ask'],
                    }
                except Exception as e:
                    log_warn(f"⚠️  获取 {outcome} 订单簿失败: {e}")

            if 'UP' not in results or 'DOWN' not in results:
                log_warn("⚠️  无法获取完整的 UP/DOWN 价格，跳过")
                return None

            # 用 BTC 实际价格生成方向信号 / Generate signal from real BTC price
            signal = self.strategy.generate_signal()

            up_ask = results['UP']['ask']
            down_ask = results['DOWN']['ask']
            up_token_id = results['UP']['token_id']
            down_token_id = results['DOWN']['token_id']

            # 决定是否下注 / Decide whether to bet
            bet = self.strategy.decide_bet(
                signal,
                up_token_ask=up_ask,
                down_token_ask=down_ask,
                up_token_id=up_token_id,
                down_token_id=down_token_id,
            )

            return {
                'signal': signal,
                'bet': bet,
                'up': results['UP'],
                'down': results['DOWN'],
            }

        except Exception as e:
            log_error(f"❌ 市场分析错误: {e}")
            return None
    
    async def execute_directional_bet(self, market, analysis) -> List[Dict]:
        """
        执行方向性单边下注（替代原网格交易）。
        Execute a single directional bet on one outcome (UP or DOWN).
        Never bets on both sides simultaneously.
        """
        try:
            if not analysis:
                return []

            bet = analysis.get('bet')
            if not bet:
                log_info("⏭️  无下注决策，跳过此市场")
                return []

            condition_id = market.get('condition_id', 'unknown')
            token_id = bet['token_id']
            side = bet['side'].lower()
            price = bet['price']
            size = bet['size']
            outcome = bet['outcome']

            log_info(
                f"🎯 执行下注: {outcome} {side.upper()} "
                f"@ {price:.4f} × {size} USDC"
            )

            order_id = self.engine.place_order(token_id, side, price, size)

            # 持久化交易记录 / Persist trade record
            self.db.save_trade({
                'order_id': order_id,
                'token_id': token_id,
                'side': side,
                'price': price,
                'size': size,
                'timestamp': datetime.now().isoformat(),
            })

            # 标记该市场已下注 / Mark market as bet on
            self.bet_markets.add(condition_id)

            return [{
                'outcome': outcome,
                'side': side,
                'price': price,
                'size': size,
                'order_id': order_id,
            }]

        except Exception as e:
            log_error(f"❌ 执行下注失败: {e}")
            return []

    # 保持旧方法名以向后兼容 / Keep old name for backward compatibility
    async def execute_grid_trades(self, market, analysis):
        return await self.execute_directional_bet(market, analysis)
    
    async def run_cycle(self):
        """
        运行一个交易检查周期（约 30 秒）。
        Run one trading check cycle (~30 seconds).
        """
        self.total_cycles += 1
        cycle_start = datetime.now()

        print("\n" + "="*80)
        print(f"🔄 交易周期 #{self.total_cycles} - {cycle_start.strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*80)

        try:
            # 找到可交易的市场 / Find tradable markets
            tradable = self.find_tradable_markets()
            log_info(f"找到 {len(tradable)} 个 BTC 可交易市场")

            if not tradable:
                log_warn("⚠️  未找到任何 BTC 可交易市场")
                return

            # 优先尝试活跃且接受订单的市场
            active_only = self.filter_by_status(tradable, 'active_only')
            if active_only:
                markets_to_trade = active_only
                print(f"✅ 找到 {len(active_only)} 个活跃市场（正在接受订单）")
            else:
                accepting = self.filter_by_status(tradable, 'accepting')
                if accepting:
                    markets_to_trade = accepting
                    print(f"⚠️  找到 {len(accepting)} 个接受订单的市场")
                else:
                    markets_to_trade = self.filter_by_status(tradable, 'any')[:5]
                    print(f"📌 演示模式：显示前 {len(markets_to_trade)} 个 BTC 市场")

            trades_total = 0
            for idx, market in enumerate(markets_to_trade, 1):
                market_question = market.get('question', 'Unknown')[:70]
                condition_id = market.get('condition_id', '')

                print(f"\n📊 市场 {idx}/{len(markets_to_trade)}: {market_question}")

                # 跳过已下注的市场 / Skip markets already bet on
                if condition_id and condition_id in self.bet_markets:
                    print(f"   ⏭️  此市场已下注，跳过")
                    continue

                # 检查市场是否在入场时间窗口内 / Check market entry window
                created_at = market.get('created_at')
                if not self.strategy.should_enter_market(created_at):
                    print(f"   ⏳ 市场已过入场窗口，跳过")
                    continue

                # 分析市场并生成信号 / Analyze market and generate signal
                analysis = await self.analyze_market(market)

                if analysis:
                    signal = analysis.get('signal', 'SKIP')
                    up_data = analysis.get('up', {})
                    down_data = analysis.get('down', {})

                    signal_emoji = {"UP": "🟢", "DOWN": "🔴", "SKIP": "⚪"}.get(signal, "❓")
                    print(f"\n   📈 BTC 信号: {signal_emoji} {signal}")
                    print(f"   💰 UP  token — BID={up_data.get('bid', 0):.4f}  ASK={up_data.get('ask', 0):.4f}")
                    print(f"   💰 DOWN token — BID={down_data.get('bid', 0):.4f}  ASK={down_data.get('ask', 0):.4f}")

                    # 执行方向性下注 / Execute directional bet
                    trades = await self.execute_directional_bet(market, analysis)

                    if trades:
                        print(f"\n   ✅ 执行了 {len(trades)} 笔下注")
                        trades_total += len(trades)
                        for trade in trades:
                            print(
                                f"     • {trade['outcome']} {trade['side'].upper()} "
                                f"@ {trade['price']:.4f} × {trade['size']} USDC"
                            )
                    else:
                        print("   ⚪ 无下注（信号不足或赔率不佳）")
                else:
                    print("   ⚠️  无法分析此市场")

            # 显示周期统计 / Show cycle statistics
            stats = self.engine.get_statistics()
            print(f"\n📊 周期统计:")
            print(f"   本周期下注: {trades_total}")
            print(f"   总订单: {stats['total_orders']}")
            print(f"   成交: {stats['filled_orders']}")
            print(f"   未实现PnL: {stats['unrealized_pnl']:.4f}")

        except Exception as e:
            log_error(f"❌ 周期执行失败: {e}")
            import traceback
            traceback.print_exc()
    
    async def continuous_trading_loop(self):
        """连续交易主循环 / Main continuous trading loop"""
        print("""
╔══════════════════════════════════════════════════════════════════════╗
║        Polymarket - 连续方向性投注机器人（EMA + ATR 策略）           ║
║                   🎯 目标: 基于 BTC 趋势单边下注                     ║
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
    """主入口 / Main entry point"""
    import os
    from lib.config import Config

    config = Config()

    # 创建方向性投注机器人 / Create directional betting bot
    bot = ContinuousGridTrader(dry_run=config.dry_run, config_dict=config.to_dict())

    # 运行连续交易 / Run continuous trading loop
    await bot.continuous_trading_loop()


if __name__ == "__main__":
    asyncio.run(main())
