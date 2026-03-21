import asyncio
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from lib.polymarket_client import PolymarketClient
from lib.trading_engine import TradingEngine
from lib.data_persistence import DataPersistence
from lib.utils import log_info, log_error, log_warn

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")


class ImbalanceTrader:
    """Late-entry imbalance strategy for BTC 5-minute Polymarket markets.

    Instead of placing multiple grid orders on both sides, this bot:
    - Waits for a configurable delay into each 5-minute window before considering entry.
    - Only enters when one side shows a clear price dominance (implied probability above a
      configurable threshold, e.g. 0.68).
    - Places at most one primary buy per market (per condition_id).
    - Optionally places a very small hedge buy on the weak side only when the weak-side price
      is extremely low (controlled by ENABLE_HEDGE and HEDGE_MAX_PRICE).
    - Applies spread, sample count, and consecutive-confirmation filters before any entry.
    """

    def __init__(self, dry_run=True):
        from lib.config import Config
        config = Config()

        self.client = PolymarketClient()
        self.engine = TradingEngine(dry_run=dry_run)
        self.db = DataPersistence()
        self.dry_run = dry_run

        # Timing
        self.cycle_duration = 300   # 5 minutes per market cycle
        self.check_interval = 5     # seconds between polling loops

        # Strategy parameters (from config / env)
        self.entry_delay_seconds = config.entry_delay_seconds
        self.trade_window_end_seconds = config.trade_window_end_seconds
        self.dominance_threshold = config.dominance_threshold
        self.max_spread_pct = config.max_spread_pct
        self.min_samples = config.min_samples
        self.confirmation_checks = config.confirmation_checks
        self.main_notional = config.main_notional
        self.enable_hedge = config.enable_hedge
        self.hedge_notional = config.hedge_notional
        self.hedge_max_price = config.hedge_max_price

        # Per-market state
        self.market_prices: Dict[str, List[Dict]] = {}  # token_id -> price history
        self.entered_markets = set()            # condition_ids already traded
        self.imbalance_confirmations: Dict[str, int] = {}   # condition_id -> count
        self.last_imbalance_side: Dict[str, Optional[str]] = {}  # condition_id -> side

        # Statistics
        self.total_cycles = 0
        self.daily_pnl = 0.0

    # ------------------------------------------------------------------
    # Market discovery
    # ------------------------------------------------------------------

    def find_tradable_markets(self) -> List[Dict]:
        """Dynamically find current BTC 5-minute markets via Gamma API."""
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
                'market_slug': m.get('slug', event.get('slug', '')),
                'condition_id': m.get('conditionId', ''),
                'active': m.get('active', True),
                'closed': m.get('closed', False),
                'accepting_orders': m.get('acceptingOrders', False),
                'tokens': [
                    {'token_id': clob_token_ids[0], 'outcome': 'UP'},
                    {'token_id': clob_token_ids[1], 'outcome': 'DOWN'},
                ],
                'min_order_size': float(m.get('orderMinSize', 5)),
                'tick_size': float(m.get('orderPriceMinTickSize', 0.01)),
            })

        log_info(f"找到 {len(tradable)} 个 BTC 5分钟可交易市场")
        return tradable

    def filter_by_status(self, markets: List[Dict], status: str = 'any') -> List[Dict]:
        """Filter markets by status."""
        if status == 'active_only':
            return [m for m in markets
                    if m.get('active', False)
                    and not m.get('closed', True)
                    and m.get('accepting_orders', False)]
        if status == 'accepting':
            return [m for m in markets if m.get('accepting_orders', False)]
        if status == 'active':
            return [m for m in markets if m.get('active', False)]
        return markets  # 'any'

    # ------------------------------------------------------------------
    # Market timing helpers
    # ------------------------------------------------------------------

    def _get_market_start_time(self, market: Dict) -> Optional[float]:
        """Derive market start epoch from the slug (btc-updown-5m-{epoch}).

        Returns the epoch in seconds if parseable, otherwise None.
        """
        slug = market.get('market_slug', '')
        parts = slug.rsplit('-', 1)
        if len(parts) == 2:
            try:
                return float(parts[1])
            except ValueError:
                pass
        return None

    def _get_seconds_into_market(self, market: Dict) -> Optional[float]:
        """Return how many seconds we are into the 5-minute window, or None."""
        start = self._get_market_start_time(market)
        if start is None:
            return None
        return time.time() - start

    def _check_trade_window(self, market: Dict) -> Tuple[bool, str]:
        """Return (ok, reason) for whether we are in the valid trade window.

        Valid window: [entry_delay_seconds, trade_window_end_seconds] from market start.
        """
        elapsed = self._get_seconds_into_market(market)
        if elapsed is None:
            log_warn("无法从 slug 推断市场开始时间，跳过时间窗口检查")
            return True, "timing_unknown"
        if elapsed < self.entry_delay_seconds:
            return False, (
                f"市场开启仅 {elapsed:.0f}s，等待至少 {self.entry_delay_seconds}s 后入场"
            )
        if elapsed > self.trade_window_end_seconds:
            return False, (
                f"市场已运行 {elapsed:.0f}s，超出交易窗口上限 {self.trade_window_end_seconds}s"
            )
        return True, f"在交易窗口内 ({elapsed:.0f}s / {self.cycle_duration}s)"

    # ------------------------------------------------------------------
    # Market analysis
    # ------------------------------------------------------------------

    async def analyze_market(self, market: Dict) -> Optional[Dict]:
        """Fetch orderbook data, compute metrics, and return per-outcome analysis dict."""
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

                    # Accumulate price history (capped at 30 snapshots)
                    if token_id not in self.market_prices:
                        self.market_prices[token_id] = []
                    self.market_prices[token_id].append({
                        'price': prices['mid'],
                        'bid': prices['bid'],
                        'ask': prices['ask'],
                        'timestamp': datetime.now(),
                    })
                    if len(self.market_prices[token_id]) > 30:
                        self.market_prices[token_id].pop(0)

                    # Persist price snapshot for later evaluation
                    self.db.save_price(
                        token_id=token_id,
                        price=prices['mid'],
                        bid=prices['bid'],
                        ask=prices['ask'],
                        timestamp=datetime.now().isoformat(),
                    )

                    spread = prices['ask'] - prices['bid']
                    spread_pct = spread / prices['mid'] if prices['mid'] > 0 else 1.0
                    volatility = self._calculate_volatility(token_id)
                    trend = self._calculate_trend(token_id)
                    samples = len(self.market_prices[token_id])

                    results[outcome] = {
                        'token_id': token_id,
                        'price': prices['mid'],
                        'bid': prices['bid'],
                        'ask': prices['ask'],
                        'spread': spread,
                        'spread_pct': spread_pct,
                        'volatility': volatility,
                        'trend': trend,
                        'samples': samples,
                    }

                except Exception as e:
                    log_warn(f"分析 {outcome} token 失败: {e}")

            return results if results else None

        except Exception as e:
            log_error(f"市场分析错误: {e}")
            return None

    def _calculate_volatility(self, token_id: str) -> float:
        """Compute normalised price volatility (std-dev / mean)."""
        history = self.market_prices.get(token_id, [])
        if len(history) < 2:
            return 0.0
        prices = [p['price'] for p in history]
        avg = sum(prices) / len(prices)
        variance = sum((p - avg) ** 2 for p in prices) / len(prices)
        return (variance ** 0.5) / avg if avg > 0 else 0.0

    def _calculate_trend(self, token_id: str) -> float:
        """Compute normalised price trend over the stored window."""
        history = self.market_prices.get(token_id, [])
        if len(history) < 5:
            return 0.0
        first = history[0]['price']
        last = history[-1]['price']
        return (last - first) / first if first > 0 else 0.0

    # ------------------------------------------------------------------
    # Signal / filter logic
    # ------------------------------------------------------------------

    def _detect_imbalance(self, analysis: Dict) -> Optional[str]:
        """Detect which side is dominant (implied price >= dominance_threshold).

        Returns 'UP', 'DOWN', or None when no dominant side is found.
        """
        up_data = analysis.get('UP')
        down_data = analysis.get('DOWN')
        if not up_data or not down_data:
            return None

        if up_data['price'] >= self.dominance_threshold:
            return 'UP'
        if down_data['price'] >= self.dominance_threshold:
            return 'DOWN'
        return None

    def _check_filters(self, analysis: Dict, dominant_side: str) -> Tuple[bool, str]:
        """Apply pre-trade spread and sample-count filters.

        Returns (ok, reason).
        """
        data = analysis.get(dominant_side)
        if not data:
            return False, f"缺少 {dominant_side} 数据"

        if data['samples'] < self.min_samples:
            return False, (
                f"样本数不足 ({data['samples']} < {self.min_samples})"
            )
        if data['spread_pct'] > self.max_spread_pct:
            return False, (
                f"{dominant_side} 点差过大 "
                f"({data['spread_pct']:.3f} > {self.max_spread_pct})"
            )
        return True, "过滤通过"

    def _update_confirmation(
        self, condition_id: str, dominant_side: Optional[str]
    ) -> int:
        """Track consecutive confirmations of the same dominant side.

        - When no dominant side is detected (None), the counter resets to 0.
        - When a dominant side is first detected or changes, the counter resets to 1
          (the current poll counts as the first confirmation).
        - Subsequent polls with the same side increment the counter.
        Returns the current confirmation count.
        """
        last_side = self.last_imbalance_side.get(condition_id)
        if dominant_side is None:
            self.imbalance_confirmations[condition_id] = 0
            self.last_imbalance_side[condition_id] = None
        elif dominant_side != last_side:
            # New side detected — start fresh at 1
            self.imbalance_confirmations[condition_id] = 1
            self.last_imbalance_side[condition_id] = dominant_side
        else:
            self.imbalance_confirmations[condition_id] = (
                self.imbalance_confirmations.get(condition_id, 0) + 1
            )
        return self.imbalance_confirmations.get(condition_id, 0)

    # ------------------------------------------------------------------
    # Trade execution
    # ------------------------------------------------------------------

    async def execute_imbalance_trade(
        self, market: Dict, analysis: Dict, dominant_side: str
    ) -> List[Dict]:
        """Execute a single directional buy on the dominant side.

        Optionally places a small hedge buy on the weak side when ENABLE_HEDGE is
        true and the weak-side price is <= HEDGE_MAX_PRICE.
        """
        trades_executed = []
        condition_id = market.get('condition_id', '')
        market_slug = market.get('market_slug', '')

        # --- Primary directional buy ---
        main_data = analysis[dominant_side]
        token_id = main_data['token_id']
        buy_price = main_data['ask']   # limit order placed at ask to cross the spread
        size = self.main_notional

        order_id = self.engine.place_order(token_id, 'buy', buy_price, size)
        self.db.save_trade({
            'order_id': order_id,
            'token_id': token_id,
            'side': 'buy',
            'price': buy_price,
            'size': size,
            'timestamp': datetime.now().isoformat(),
            'outcome': dominant_side,
            'market_slug': market_slug,
        })
        log_info(
            f"主力买入: {dominant_side} @ {buy_price:.4f}  size={size}  "
            f"spread_pct={main_data['spread_pct']:.3f}  "
            f"samples={main_data['samples']}"
        )
        trades_executed.append({
            'outcome': dominant_side,
            'side': 'buy',
            'price': buy_price,
            'size': size,
            'type': 'main',
        })

        # --- Optional hedge buy on the weak side ---
        if self.enable_hedge:
            weak_side = 'DOWN' if dominant_side == 'UP' else 'UP'
            weak_data = analysis.get(weak_side)
            if weak_data and weak_data['price'] <= self.hedge_max_price:
                hedge_price = weak_data['ask']
                hedge_size = self.hedge_notional
                hedge_order_id = self.engine.place_order(
                    weak_data['token_id'], 'buy', hedge_price, hedge_size
                )
                self.db.save_trade({
                    'order_id': hedge_order_id,
                    'token_id': weak_data['token_id'],
                    'side': 'buy',
                    'price': hedge_price,
                    'size': hedge_size,
                    'timestamp': datetime.now().isoformat(),
                    'outcome': weak_side,
                    'market_slug': market_slug,
                })
                log_info(
                    f"对冲买入: {weak_side} @ {hedge_price:.4f}  size={hedge_size}  "
                    f"(价格={weak_data['price']:.4f} <= hedge_max={self.hedge_max_price})"
                )
                trades_executed.append({
                    'outcome': weak_side,
                    'side': 'buy',
                    'price': hedge_price,
                    'size': hedge_size,
                    'type': 'hedge',
                })
            elif weak_data:
                log_info(
                    f"对冲跳过: {weak_side} 价格 {weak_data['price']:.4f} "
                    f"> hedge_max {self.hedge_max_price}"
                )

        return trades_executed

    # ------------------------------------------------------------------
    # Main trading cycle
    # ------------------------------------------------------------------

    async def run_cycle(self):
        """Run one trading cycle: discover markets, analyse, and conditionally trade."""
        self.total_cycles += 1
        cycle_start = datetime.now()

        print("\n" + "=" * 80)
        print(f"🔄 交易周期 #{self.total_cycles} - {cycle_start.strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 80)

        try:
            tradable = self.find_tradable_markets()
            if not tradable:
                log_warn("未找到任何 BTC 5分钟可交易市场")
                return

            active_only = self.filter_by_status(tradable, 'active_only')
            if active_only:
                markets_to_trade = active_only
                print(f"✅ 找到 {len(active_only)} 个活跃市场")
            else:
                accepting = self.filter_by_status(tradable, 'accepting')
                markets_to_trade = accepting if accepting else self.filter_by_status(tradable, 'any')[:5]
                print(f"⚠️  找到 {len(markets_to_trade)} 个市场（宽松筛选）")

            trades_total = 0
            for idx, market in enumerate(markets_to_trade, 1):
                condition_id = market.get('condition_id', '')
                market_question = market.get('question', 'Unknown')[:70]

                print(f"\n📊 市场 {idx}/{len(markets_to_trade)}: {market_question}")

                # Skip markets we have already traded this run
                if condition_id and condition_id in self.entered_markets:
                    log_info("  ⏭ 本市场已入场，跳过重复交易")
                    continue

                # Time-window check
                window_ok, window_reason = self._check_trade_window(market)
                print(f"   ⏰ 时间窗口: {window_reason}")
                if not window_ok:
                    log_info(f"  ⏭ 跳过（时间窗口外）: {window_reason}")
                    continue

                # Gather price data and compute metrics
                analysis = await self.analyze_market(market)
                if not analysis:
                    log_warn("  ⚠️  无法分析此市场")
                    continue

                print("\n   📈 市场分析结果:")
                for outcome, data in analysis.items():
                    print(
                        f"     {outcome}: 价格={data['price']:.4f}  "
                        f"bid={data['bid']:.4f}  ask={data['ask']:.4f}  "
                        f"spread_pct={data['spread_pct']:.3f}  "
                        f"samples={data['samples']}"
                    )

                # Detect imbalance and update confirmation counter
                dominant_side = self._detect_imbalance(analysis)
                confirmations = self._update_confirmation(condition_id, dominant_side)

                if dominant_side is None:
                    up_price = analysis.get('UP', {}).get('price', 0)
                    down_price = analysis.get('DOWN', {}).get('price', 0)
                    log_info(
                        f"  ⏭ 未检测到价格失衡 "
                        f"(UP={up_price:.4f}, DOWN={down_price:.4f}, "
                        f"阈值={self.dominance_threshold})"
                    )
                    continue

                print(
                    f"   🎯 检测到失衡: {dominant_side} 主导  "
                    f"(连续确认: {confirmations}/{self.confirmation_checks})"
                )

                if confirmations < self.confirmation_checks:
                    log_info(
                        f"  ⏳ 等待更多确认 ({confirmations}/{self.confirmation_checks})，暂不入场"
                    )
                    continue

                # Pre-trade filters (spread, samples)
                filters_ok, filter_reason = self._check_filters(analysis, dominant_side)
                if not filters_ok:
                    log_info(f"  ⏭ 过滤未通过: {filter_reason}")
                    continue

                print(f"   ✅ 所有过滤通过: {filter_reason}")

                # Execute the trade
                trades = await self.execute_imbalance_trade(market, analysis, dominant_side)
                if trades:
                    if condition_id:
                        self.entered_markets.add(condition_id)
                    trades_total += len(trades)
                    for t in trades:
                        flag = "🟢" if t['type'] == 'main' else "🔵"
                        print(
                            f"   {flag} [{t['type'].upper()}] {t['outcome']} BUY "
                            f"@ {t['price']:.4f}  size={t['size']}"
                        )
                else:
                    log_warn("  ⚠️  交易执行失败")

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
        """Continuously run the trading cycle until interrupted."""
        print("""
╔══════════════════════════════════════════════════════════════════════╗
║        Polymarket - 晚期失衡策略 BTC 5 分钟交易机器人               ║
║              🎯 目标: 精准单边入场，降低过度交易                     ║
╚══════════════════════════════════════════════════════════════════════╝
        """)

        mode = "模拟交易（Dry Run）" if self.dry_run else "🔴 真实交易（注意风险！）"
        print(f"⚠️  运行模式: {mode}")
        print(f"⏰ 入场延迟: {self.entry_delay_seconds}s | 交易窗口截止: {self.trade_window_end_seconds}s")
        print(f"🎯 失衡阈值: {self.dominance_threshold} | 确认次数: {self.confirmation_checks}")
        print(f"📉 最大点差: {self.max_spread_pct:.1%} | 最小样本: {self.min_samples}")
        print(
            f"💵 主力规模: {self.main_notional} USDC | "
            f"对冲: {'开启 (' + str(self.hedge_notional) + ' USDC)' if self.enable_hedge else '关闭'}"
        )
        print()

        while True:
            try:
                cycle_start = datetime.now()
                await self.run_cycle()

                elapsed = (datetime.now() - cycle_start).total_seconds()
                wait_time = max(self.cycle_duration - elapsed, self.check_interval)
                print(f"\n⏳ 本周期耗时: {elapsed:.1f}s，等待 {wait_time:.1f}s...")
                print("=" * 80)
                await asyncio.sleep(wait_time)

            except KeyboardInterrupt:
                self.shutdown()
                break
            except Exception as e:
                log_error(f"主循环错误: {e}")
                await asyncio.sleep(10)

    def shutdown(self):
        """Gracefully shut down the bot and print final statistics."""
        print("\n" + "=" * 80)
        print("🛑 机器人关闭")
        print("=" * 80)

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
   交易笔数: {performance.get('total_trades', 0)}
   平均名义价值: {performance.get('avg_pnl', 0):.4f}
   最高名义价值: {performance.get('max_pnl', 0):.4f}
   最低名义价值: {performance.get('min_pnl', 0):.4f}
        """)

        self.db.close()


async def main():
    """Main entry point."""
    from lib.config import Config

    config = Config()
    bot = ImbalanceTrader(dry_run=config.dry_run)
    await bot.continuous_trading_loop()


if __name__ == "__main__":
    asyncio.run(main())
