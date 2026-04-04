import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional
from lib.config import Config
from lib.polymarket_client import PolymarketClient
from lib.trading_engine import TradingEngine
from lib.utils import log_info, log_error, log_warn

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")

class MarketExpiredError(Exception):
    """市场已结算，token失效"""
    pass

class ContinuousGridTrader:
    """连续5分钟周期BTC网格交易机器人"""

    def __init__(self, dry_run=True, order_size=5.0, check_interval=5):
        self.client = PolymarketClient()
        self.engine = TradingEngine(dry_run=dry_run)
        self.dry_run = dry_run
        self.order_size = order_size

        self.check_interval = max(int(check_interval), 1)
        self.total_cycles = 0
        self.market_prices = {}     # token_id -> [价格历史]

    # ─────────────────────────────────────────
    # 市场选择（以Polymarket时间为准）
    # ─────────────────────────────────────────
    def find_active_market(self) -> Optional[Dict]:
        """获取当前活跃的BTC 5分钟市场（直接读Polymarket API）"""
        import json as _json
        event = self.client.get_current_btc_5m_market()
        if not event:
            return None

        for m in event.get('markets', []):
            if not m.get('acceptingOrders', False):
                continue
            if m.get('closed', False):
                continue

            raw = m.get('clobTokenIds', '[]')
            token_ids = _json.loads(raw) if isinstance(raw, str) else raw
            if len(token_ids) < 2:
                continue

            return {
                'title':    event.get('title', ''),
                'question': m.get('question', ''),
                'up_token':   token_ids[0],
                'down_token': token_ids[1],
                'tick_size':  float(m.get('orderPriceMinTickSize', 0.01)),
                'min_size':   float(m.get('orderMinSize', 5)),
            }
        return None

    # ─────────────────────────────────────────
    # 价格分析（做市商视角）
    # ─────────────────────────────────────────
    def get_prices(self, market: Dict) -> Optional[Dict]:
        """获取UP/DOWN当前价格，验证互补性"""
        try:
            up_book   = self.client.get_orderbook(market['up_token'])
            down_book = self.client.get_orderbook(market['down_token'])

            up_p   = self.client.calculate_mid_price(up_book)
            down_p = self.client.calculate_mid_price(down_book)

            # mid为None说明orderbook单边或为空，跳过
            if up_p['mid'] is None or down_p['mid'] is None:
                log_warn("orderbook异常，跳过本轮")
                return None

            total = up_p['mid'] + down_p['mid']
            log_info(f"UP={up_p['mid']:.4f} DOWN={down_p['mid']:.4f} 合计={total:.4f}")

            # UP+DOWN应接近1（允许±0.05误差）
            if not (0.95 <= total <= 1.05):
                log_warn(f"价格互补性异常: UP+DOWN={total:.4f}，跳过")
                return None

            return {
                'up_bid':   up_p['bid'],   'up_ask':   up_p['ask'],   'up_mid':   up_p['mid'],
                'down_bid': down_p['bid'], 'down_ask': down_p['ask'], 'down_mid': down_p['mid'],
                'spread_up':   up_p['ask']   - up_p['bid'],
                'spread_down': down_p['ask'] - down_p['bid'],
                'timestamp': datetime.now(),
            }
        except Exception as e:
            log_error(f"获取价格失败: {e}")
            if "404" in str(e) or "Not Found" in str(e):
                raise MarketExpiredError(f"市场token已失效(404): {e}")
            return None

    def record_prices(self, token_id: str, mid: float):
        """记录价格历史（最多保留30个点）"""
        if token_id not in self.market_prices:
            self.market_prices[token_id] = []
        self.market_prices[token_id].append(mid)
        if len(self.market_prices[token_id]) > 30:
            self.market_prices[token_id].pop(0)

    def get_volatility(self, token_id: str) -> float:
        """计算价格波动率"""
        prices = self.market_prices.get(token_id, [])
        if len(prices) < 3:
            return 0.0
        avg = sum(prices) / len(prices)
        variance = sum((p - avg) ** 2 for p in prices) / len(prices)
        return (variance ** 0.5) / avg if avg > 0 else 0.0

    # ─────────────────────────────────────────
    # 信号生成（做市商策略）
    # ─────────────────────────────────────────
    def generate_signal(self, prices: Dict, market: Dict) -> Dict:
        """
        做市商策略：
        - spread足够大（>1个tick）→ 在bid/ask之间挂单
        - 价格接近0.5时最佳（不偏向任何方向）
        - 价格极端（<0.05或>0.95）→ 市场快结算，不交易
        """
        tick = market['tick_size']
        min_spread = tick * 1  # 最小有效价差（需要3个tick才有利润空间）

        signal = {
            'trade_up':   False,
            'trade_down': False,
            'reason':     '',
        }

        up_mid   = prices['up_mid']
        down_mid = prices['down_mid']

        # 价格极端判断（市场快结算）
        if up_mid < 0.005 or up_mid > 0.995:
            signal['reason'] = f"UP价格极端({up_mid:.3f})，市场可能快结算，不交易"
            return signal

        # 价差判断
        if prices['spread_up'] >= min_spread:
            signal['trade_up'] = True
        if prices['spread_down'] >= min_spread:
            signal['trade_down'] = True

        if signal['trade_up'] or signal['trade_down']:
            signal['reason'] = (
                f"价差UP={prices['spread_up']:.4f} "
                f"DOWN={prices['spread_down']:.4f} "
                f"最小有效价差={min_spread:.4f}"
            )
        else:
            signal['reason'] = f"价差过小，不交易"

        return signal

    # ─────────────────────────────────────────
    # 执行交易（dry_run下模拟）
    # ─────────────────────────────────────────
    def execute_trades(self, market: Dict, prices: Dict, signal: Dict):
        """在bid/ask挂单做市"""
        try:
            market_min_size = float(market.get("min_size", self.order_size))
        except (TypeError, ValueError):
            market_min_size = self.order_size
        order_size = max(self.order_size, market_min_size)
        tick = market['tick_size']
        trades = []

        if signal['trade_up']:
            spread = prices['spread_up']
            if spread >= tick * 2:
                # 价差够大：内缩1tick，赚更多
                buy_price  = round(prices['up_bid'] + tick, 4)
                sell_price = round(prices['up_ask'] - tick, 4)
            else:
                # 价差只有1tick：直接在bid买、ask卖，赚整个价差
                buy_price  = round(prices['up_bid'], 4)
                sell_price = round(prices['up_ask'], 4)

            if buy_price < sell_price:
                self.engine.place_order(market['up_token'], 'buy',  buy_price,  order_size)
                self.engine.place_order(market['up_token'], 'sell', sell_price, order_size)
                trades.append(f"UP  BUY@{buy_price:.4f} SELL@{sell_price:.4f} spread={spread:.4f}")

        if signal['trade_down']:
            spread = prices['spread_down']
            if spread >= tick * 2:
                buy_price  = round(prices['down_bid'] + tick, 4)
                sell_price = round(prices['down_ask'] - tick, 4)
            else:
                buy_price  = round(prices['down_bid'], 4)
                sell_price = round(prices['down_ask'], 4)

            if buy_price < sell_price:
                self.engine.place_order(market['down_token'], 'buy',  buy_price,  order_size)
                self.engine.place_order(market['down_token'], 'sell', sell_price, order_size)
                trades.append(f"DOWN BUY@{buy_price:.4f} SELL@{sell_price:.4f} spread={spread:.4f}")

        return trades

    # ─────────────────────────────────────────
    # 主循环
    # ─────────────────────────────────────────
    async def run(self):
        print("""
╔══════════════════════════════════════════════════════╗
║    Polymarket BTC 5分钟 做市商机器人                 ║
╚══════════════════════════════════════════════════════╝""")
        mode = "🟡 DRY RUN（模拟）" if self.dry_run else "🔴 真实交易"
        print(f"模式: {mode}\n")

        current_market = None
        market_start   = None

        while True:
            try:
                now = datetime.now()

                # ── 每个5分钟窗口开始时刷新市场 ──
                need_refresh = (
                    current_market is None or
                    market_start is None or
                    (now - market_start).total_seconds() >= 290  # 提前10秒换市场
                )

                if need_refresh:
                    print(f"\n{'='*60}")
                    print(f"🔍 [{now.strftime('%H:%M:%S')}] 查找当前活跃市场...")
                    new_market = self.find_active_market()
                    if new_market:
                        current_market = new_market
                        # 用市场真实开始时间（从slug解析UTC时间戳）
                        try:
                            import re
                            slug = new_market.get('slug', '') or new_market.get('title', '')
                            # slug格式: btc-updown-5m-1773840300
                            m = re.search(r'btc-updown-5m-(\d+)', slug)
                            if m:
                                real_start_ts = int(m.group(1))
                                from datetime import timezone
                                market_start = datetime.fromtimestamp(real_start_ts)
                                log_info(f"市场真实开始时间: {market_start.strftime('%H:%M:%S')} (已过{(now-market_start).total_seconds():.0f}s)")
                            else:
                                market_start = now
                        except Exception:
                            market_start = now
                        self.market_prices = {}  # 重置价格历史
                        self.total_cycles += 1
                        print(f"✅ 周期#{self.total_cycles}: {current_market['title']}")
                    else:
                        print("⚠️  未找到活跃市场，10秒后重试...")
                        await asyncio.sleep(10)
                        continue

                # ── 获取价格 ──
                try:
                    prices = self.get_prices(current_market)
                except MarketExpiredError as e:
                    log_warn(f"⚠️  市场已结算，强制刷新市场: {e}")
                    current_market = None  # 强制下次循环刷新市场
                    market_start = None
                    await asyncio.sleep(5)
                    continue
                if not prices:
                    await asyncio.sleep(self.check_interval)
                    continue

                # 记录价格历史
                self.record_prices(current_market['up_token'],   prices['up_mid'])
                self.record_prices(current_market['down_token'], prices['down_mid'])

                vol_up   = self.get_volatility(current_market['up_token'])
                elapsed  = (now - market_start).total_seconds()

                print(f"\n[{now.strftime('%H:%M:%S')}] +{elapsed:.0f}s "
                      f"UP={prices['up_mid']:.4f}({prices['spread_up']:.4f}) "
                      f"DOWN={prices['down_mid']:.4f}({prices['spread_down']:.4f}) "
                      f"vol={vol_up:.6f}")

                # ── 生成信号并执行 ──
                signal = self.generate_signal(prices, current_market)
                print(f"  信号: {signal['reason']}")

                if signal['trade_up'] or signal['trade_down']:
                    trades = self.execute_trades(current_market, prices, signal)
                    for t in trades:
                        print(f"  ✅ {t}")

                # ── 统计 ──
                stats = self.engine.get_statistics()
                print(f"  累计: 订单={stats['total_orders']} 成交={stats['filled_orders']}")

                await asyncio.sleep(self.check_interval)

            except KeyboardInterrupt:
                print("\n🛑 用户终止")
                break
            except Exception as e:
                log_error(f"主循环错误: {e}")
                import traceback; traceback.print_exc()
                await asyncio.sleep(10)

async def main():
    config = Config()
    bot = ContinuousGridTrader(
        dry_run=config.dry_run,
        order_size=config.order_size,
        check_interval=config.check_interval_sec,
    )
    await bot.run()

if __name__ == "__main__":
    asyncio.run(main())
