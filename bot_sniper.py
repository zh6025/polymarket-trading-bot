#!/usr/bin/env python3
"""
bot_sniper.py — 末端狙击机器人
策略：在BTC 5分钟窗口结束前约30秒入场，只在55%-60%份额价格区间买入，
结合Binance实时价格动量确认，使用半Kelly公式计算下注比例。
"""
import asyncio
import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler
from typing import Optional

from lib.config import Config
from lib.utils import log_info, log_error, log_warn
from lib.polymarket_client import PolymarketClient
from lib.bot_state import BotState
from lib.binance_feed import BinanceFeed
from lib.sniper_strategy import SniperStrategy
from lib.notifier import Notifier


def _setup_logging():
    """配置控制台 + 滚动文件日志。"""
    handlers = [logging.StreamHandler()]
    log_dir = os.environ.get('LOG_DIR', 'logs')
    try:
        os.makedirs(log_dir, exist_ok=True)
        fh = RotatingFileHandler(
            os.path.join(log_dir, 'bot.log'),
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
        )
        handlers.append(fh)
    except Exception as e:
        # 若挂载点只读则降级为只用 stdout
        print(f"[WARN] 无法初始化文件日志: {e}", file=sys.stderr)
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] %(message)s",
        handlers=handlers,
        force=True,
    )


_setup_logging()
logger = logging.getLogger(__name__)

# 每次轮询间隔（秒）
POLL_INTERVAL_SEC = 5


def _coerce_list(val):
    """outcomes / outcomePrices / clobTokenIds 在 Gamma 返回里有时是 JSON 字符串，需要解析。"""
    if val is None:
        return []
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        import json as _json
        try:
            parsed = _json.loads(val)
            return parsed if isinstance(parsed, list) else []
        except (ValueError, TypeError):
            return []
    return []


def _extract_up_down(event: dict):
    """
    从 Gamma event 里抽取 UP/DOWN 的份额价格和 CLOB token id，兼容两种结构：
      A) 新结构：单 market，outcomes=["Up","Down"]，outcomePrices/clobTokenIds 平行数组
      B) 旧结构：两个子 market，用 groupItemTitle 区分 UP/DOWN，outcomePrices[0] 是 YES 价
    返回 (up_price, down_price, up_token_id, down_token_id)；缺失项为 None。
    """
    markets = event.get('markets', []) or []
    active = [m for m in markets
              if m.get('acceptingOrders', False) and not m.get('closed', True)]
    if not active:
        return None, None, None, None

    # ---- A) 单市场 + 2 outcomes ----
    if len(active) == 1:
        m = active[0]
        outcomes = _coerce_list(m.get('outcomes'))
        prices = _coerce_list(m.get('outcomePrices'))
        tokens = _coerce_list(m.get('clobTokenIds'))
        up_idx = down_idx = None
        for i, name in enumerate(outcomes):
            n = str(name).strip().upper()
            if n == 'UP' and up_idx is None:
                up_idx = i
            elif n == 'DOWN' and down_idx is None:
                down_idx = i
        # 默认 fallback：index 0=Up, 1=Down
        if up_idx is None and down_idx is None and len(outcomes) >= 2:
            up_idx, down_idx = 0, 1

        def _f(arr, i):
            if i is None or i >= len(arr):
                return None
            try:
                return float(arr[i])
            except (TypeError, ValueError):
                return None

        def _t(arr, i):
            if i is None or i >= len(arr):
                return None
            return str(arr[i]) if arr[i] else None

        return _f(prices, up_idx), _f(prices, down_idx), _t(tokens, up_idx), _t(tokens, down_idx)

    # ---- B) 两个子市场 + groupItemTitle ----
    up_m = next((m for m in active if 'UP' in str(m.get('groupItemTitle', '')).upper()), None)
    down_m = next((m for m in active if 'DOWN' in str(m.get('groupItemTitle', '')).upper()), None)
    if up_m is None and down_m is None and len(active) >= 2:
        up_m, down_m = active[0], active[1]

    def _yes_price(m):
        if not m:
            return None
        prices = _coerce_list(m.get('outcomePrices'))
        if not prices:
            return None
        try:
            return float(prices[0])
        except (TypeError, ValueError):
            return None

    def _yes_token(m):
        if not m:
            return None
        tokens = _coerce_list(m.get('clobTokenIds'))
        if not tokens:
            return None
        return str(tokens[0]) if tokens[0] else None

    return _yes_price(up_m), _yes_price(down_m), _yes_token(up_m), _yes_token(down_m)


def _parse_window_open_ts(event: dict) -> Optional[int]:
    """
    从市场事件数据中解析窗口开始时间戳。
    Polymarket slug 格式: btc-updown-5m-<unix_ts>
    """
    slug = event.get('slug', '')
    try:
        ts = int(slug.split('-')[-1])
        return ts
    except (ValueError, IndexError):
        return None


class SniperBot:
    """末端狙击机器人主控"""

    def __init__(self, config: Config, client: PolymarketClient,
                 state: BotState, feed: BinanceFeed, strategy: SniperStrategy,
                 notifier: Optional[Notifier] = None):
        self.config = config
        self.client = client
        self.state = state
        self.feed = feed
        self.strategy = strategy
        self.notifier = notifier or Notifier()

    async def run(self):
        """异步主循环"""
        log_info("╔═══════════════════════════════════════════════╗")
        log_info("║   Polymarket Sniper Bot - BTC 5m End Snipe   ║")
        log_info("╚═══════════════════════════════════════════════╝")
        log_info(f"策略参数: 入场窗口=[{self.strategy.entry_window_low},{self.strategy.entry_window_high}]s "
                 f"价格区间=[{self.strategy.price_min},{self.strategy.price_max}] "
                 f"最小偏离={self.strategy.min_delta_bps}bps "
                 f"Kelly系数={self.strategy.kelly_fraction}")
        if not self.config.trading_enabled:
            log_warn("⚠️  TRADING_ENABLED=false，监控模式（不会下单）")
        elif self.config.dry_run:
            log_warn("⚠️  DRY_RUN=true，模拟模式（不会真实下单）")
        else:
            log_info("🟢 实盘模式 - 真实下单已启用")
            self.notifier.notify("实盘模式启动 - 真实下单已启用", level='warn')

        while True:
            try:
                await self._cycle()
                await self._settle_finished_windows()
            except KeyboardInterrupt:
                raise
            except Exception as e:
                log_error(f"周期异常（已捕获，继续运行）: {e}")
            await asyncio.sleep(POLL_INTERVAL_SEC)

    async def _cycle(self):
        """单次周期"""
        now = int(time.time())

        # 1. 获取Binance BTC实时价格（记录历史）
        btc_price = self.feed.get_btc_price()
        if btc_price is None:
            log_warn("⚠️  无法获取Binance BTC价格，跳过本周期")
            return
        log_info(f"💹 BTC/USDT: {btc_price:.2f}")

        # 2. 获取当前活跃的BTC 5分钟市场
        try:
            event = self.client.get_current_btc_5m_market()
        except Exception as e:
            log_error(f"获取Polymarket市场失败: {e}")
            return

        if not event:
            log_warn("⚠️  未找到活跃BTC 5分钟市场，等待下一轮")
            return

        # 3. 解析窗口信息
        window_open_ts = _parse_window_open_ts(event)
        window_end_ts = window_open_ts + 300 if window_open_ts else None
        remaining_seconds = int(window_end_ts - now) if window_end_ts else 0

        if remaining_seconds <= 0:
            log_warn(f"⏰ 窗口已结束或时间解析失败，等待新窗口 (remaining={remaining_seconds}s)")
            return

        log_info(f"📅 窗口: open_ts={window_open_ts} remaining={remaining_seconds}s")

        # 4. 如果剩余 > entry_window_high + 5s：仅记录价格，等待入场窗口
        if remaining_seconds > self.strategy.entry_window_high + 5:
            up_price_pre, down_price_pre, _, _ = _extract_up_down(event)
            up_str = f"{up_price_pre:.3f}" if up_price_pre is not None else "N/A"
            down_str = f"{down_price_pre:.3f}" if down_price_pre is not None else "N/A"
            log_info(f"⏳ 等待入场窗口 (剩余{remaining_seconds}s) | BTC={btc_price:.2f} | UP份额={up_str} DOWN份额={down_str}")
            return

        # 5. 检查该窗口是否已经入场过（持久化）
        if self.state.last_entered_window_ts == window_open_ts:
            log_info(f"✅ 本窗口已入场，等待下一窗口")
            return

        # 6. 检查风控
        can, reason = self.state.can_trade(
            daily_loss_limit=self.config.daily_loss_limit_usdc,
            daily_trade_limit=self.config.daily_trade_limit,
            consec_loss_limit=self.config.consecutive_loss_limit,
        )
        if not can:
            log_warn(f"⏸ 交易暂停: {reason}")
            return

        # 7. 解析市场价格（兼容单市场+2outcomes 与 双子市场两种结构）
        up_price, down_price, up_token_id, down_token_id = _extract_up_down(event)
        if up_price is None or down_price is None:
            log_warn("⚠️  市场子单已关闭或价格不可读，跳过")
            return
        if not up_token_id or not down_token_id:
            log_warn("⚠️  未找到 UP/DOWN 的 clob token id，跳过")
            return

        log_info(f"📊 价格: UP={up_price:.3f} DOWN={down_price:.3f}")

        # 8. 获取动量
        momentum = self.feed.get_momentum(seconds=self.strategy.momentum_secs)
        log_info(f"📈 动量({self.strategy.momentum_secs}s): "
                 f"方向={momentum['direction']} "
                 f"delta_bps={momentum['delta_bps']:.1f} "
                 f"samples={momentum['n_samples']}")

        # 9. 评估狙击信号
        signal = self.strategy.evaluate(
            remaining_seconds=remaining_seconds,
            window_open_price=btc_price,
            current_btc_price=btc_price,
            up_price=up_price,
            down_price=down_price,
            momentum=momentum,
        )
        log_info(f"🎯 信号: action={signal['action']} | {signal['reasoning']}")

        if signal['action'] == 'SKIP':
            return

        # 10. 计算下注规模（用Kelly公式调整基础下注）
        base_bet = self.config.bet_size_usdc
        kelly = signal['kelly_fraction']
        # kelly_fraction 已经是半Kelly缩放后的比例（相对于资金），用它来调整下注
        # 简单策略：bet = base_bet × min(kelly × 10, 1.5)（上限为1.5×基础下注）
        kelly_multiplier = min(kelly * 10.0, 1.5) if kelly > 0 else 1.0
        bet_size = round(base_bet * kelly_multiplier, 2)

        direction = signal['direction']
        entry_price = signal['entry_price']
        edge = signal['edge']
        estimated_prob = signal['estimated_prob']

        log_info(f"💰 下注: {direction} @ {entry_price:.3f} "
                 f"size={bet_size:.2f} USDC "
                 f"edge={edge:.3f} "
                 f"估计概率={estimated_prob:.1%}")

        # 11. 执行下单
        order_id: Optional[str] = None
        token_id = up_token_id if direction == 'UP' else down_token_id
        if not token_id:
            log_error(f"未找到 {direction} 方向的token_id，跳过")
            return

        # 计算份额数量：USDC 预算 / 价格 = 份额数（Polymarket size 是份额数）
        share_size = bet_size / entry_price if entry_price > 0 else 0

        if not self.config.dry_run and self.config.trading_enabled:
            try:
                # 余额检查
                if not self._check_balance(bet_size):
                    return

                result = self.client.place_order(
                    token_id=token_id,
                    side='BUY',
                    price=entry_price,
                    size=share_size,
                    order_type=self.config.poly_order_type,
                )
                order_id = result.get('order_id')
                if not order_id:
                    log_error(f"下单失败：未返回 order_id, 响应={result}")
                    self.notifier.notify(f"下单失败（无 order_id）: {direction} @ {entry_price}", level='error')
                    return
                log_info(f"✅ 订单已提交: {direction} @ {entry_price:.3f} x {result['size']:.4f} 份额"
                         f" (order_id={order_id})")

                # 记录持仓
                self.state.record_open_position(
                    order_id=order_id,
                    token_id=token_id,
                    direction=direction,
                    entry_price=result['price'],
                    size=result['size'],
                    window_open_ts=window_open_ts,
                    window_end_ts=window_end_ts,
                    market_slug=event.get('slug', ''),
                )

                # 启动订单监控（异步），未成交则在窗口结束前撤单
                asyncio.create_task(
                    self._monitor_order(order_id, window_end_ts)
                )
            except Exception as e:
                log_error(f"下单失败: {e}")
                self.notifier.notify(f"下单异常: {direction} @ {entry_price}: {e}", level='error')
                return
        else:
            log_info(f"🔬 DRY-RUN: {direction} @ {entry_price:.3f} x {share_size:.4f} 份额"
                     f" (~{bet_size:.2f} USDC，跳过真实下单）")

        # 12. 记录入场，防止本窗口重复入场（持久化）
        self.state.last_entered_window_ts = window_open_ts
        self.state.save(self.config.state_file)
        log_info(f"💾 入场记录已保存 | 今日交易={self.state.daily_trade_count} "
                 f"今日PnL=${self.state.daily_pnl:.2f}")

    # ------------------------------------------------------------------
    # 余额 / 订单生命周期 / 结算
    # ------------------------------------------------------------------
    def _check_balance(self, required_usdc: float) -> bool:
        """下单前检查 USDC 余额；不足则告警并跳过本次下单。"""
        try:
            ba = self.client.get_balance_allowance()
            # py_clob_client 通常返回 {'balance': '...', 'allowance': '...'}（USDC 6 位小数）
            balance_raw = float(ba.get('balance', 0)) if isinstance(ba, dict) else 0
            # USDC 是 6 位小数
            balance_usdc = balance_raw / 1_000_000 if balance_raw > 1000 else balance_raw
            allowance_raw = float(ba.get('allowance', 0)) if isinstance(ba, dict) else 0
            allowance_usdc = allowance_raw / 1_000_000 if allowance_raw > 1000 else allowance_raw
            log_info(f"💵 USDC 余额={balance_usdc:.4f} 授权额度={allowance_usdc:.4f} 需要={required_usdc:.4f}")
            if balance_usdc < required_usdc:
                msg = f"USDC 余额不足: {balance_usdc:.4f} < {required_usdc:.4f}"
                log_error(msg)
                self.notifier.notify(msg, level='error')
                return False
            if allowance_usdc < required_usdc:
                msg = (f"USDC 授权不足: {allowance_usdc:.4f} < {required_usdc:.4f}，"
                       f"请运行 scripts/setup_allowance.py")
                log_error(msg)
                self.notifier.notify(msg, level='error')
                return False
            return True
        except Exception as e:
            log_warn(f"余额检查失败（继续下单）: {e}")
            return True

    async def _monitor_order(self, order_id: str, window_end_ts: int):
        """下单后短轮询：每 1s 查询，未成交且接近窗口结束就撤单。"""
        timeout = self.config.order_fill_timeout_sec
        cancel_buffer = self.config.order_cancel_before_end_sec
        deadline = time.time() + timeout
        while True:
            try:
                info = self.client.get_order(order_id)
                status = info.get('status') if isinstance(info, dict) else None
                size_matched = float(info.get('size_matched', 0)) if isinstance(info, dict) else 0
                if status in ('MATCHED', 'FILLED', 'COMPLETE'):
                    log_info(f"🎯 订单已完全成交: {order_id} status={status}")
                    self.state.update_open_position(
                        order_id,
                        filled_size=size_matched or self.state.find_open_position(order_id).get('size', 0),
                    )
                    self.state.save(self.config.state_file)
                    return
                if status in ('CANCELED', 'CANCELLED'):
                    log_info(f"订单已取消: {order_id}")
                    self.state.update_open_position(order_id, cancelled=True, filled_size=size_matched)
                    self.state.save(self.config.state_file)
                    return
            except Exception as e:
                log_warn(f"查询订单失败: {e}")

            now = time.time()
            time_to_window_end = window_end_ts - now
            # 若到了 fill 超时，或距窗口结束不足 cancel_buffer，撤单
            if now >= deadline or time_to_window_end <= cancel_buffer:
                try:
                    self.client.cancel_order(order_id)
                    log_info(f"⏱ 订单超时/接近窗口结束，已发起撤单: {order_id}")
                    self.state.update_open_position(order_id, cancelled=True)
                    self.state.save(self.config.state_file)
                except Exception as e:
                    log_warn(f"撤单失败: {e}")
                return

            await asyncio.sleep(1)

    async def _settle_finished_windows(self):
        """扫描已结束的窗口，从链上拉成交+结果，计算真实 PnL。"""
        if not self.state.open_positions:
            return
        now = int(time.time())
        settle_after = self.config.settle_after_end_sec
        for pos in list(self.state.open_positions):
            if pos.get('settled'):
                continue
            window_end_ts = int(pos.get('window_end_ts', 0))
            if window_end_ts == 0 or now < window_end_ts + settle_after:
                continue
            order_id = pos.get('order_id')
            if not order_id:
                continue
            log_info(f"⚖️ 结算窗口 {pos.get('market_slug')} (order={order_id})")
            try:
                # 1) 拉订单成交信息
                filled_size = float(pos.get('filled_size', 0))
                avg_price = float(pos.get('entry_price', 0))
                if self.config.trading_enabled and not self.config.dry_run:
                    try:
                        info = self.client.get_order(order_id)
                        if isinstance(info, dict):
                            filled_size = float(info.get('size_matched', filled_size) or filled_size)
                            # average price 字段名因版本而异
                            ap = info.get('average_price') or info.get('price') or avg_price
                            try:
                                avg_price = float(ap)
                            except (TypeError, ValueError):
                                pass
                    except Exception as e:
                        log_warn(f"拉取订单成交信息失败: {e}")

                if filled_size <= 0:
                    log_info(f"订单未成交，结算 PnL=0: {order_id}")
                    self.state.settle_position(order_id, pnl=0.0, won=False)
                    self.state.save(self.config.state_file)
                    continue

                # 2) 拉市场结果（哪边赢）
                slug = pos.get('market_slug') or ''
                won = self._market_won(slug, pos.get('token_id', ''), pos.get('direction', ''))

                # 3) PnL = (1 - entry_price) × filled_size  if won else  -entry_price × filled_size
                if won is None:
                    log_warn(f"无法判断市场结果，延后结算: {slug}")
                    continue
                if won:
                    pnl = (1.0 - avg_price) * filled_size
                else:
                    pnl = -avg_price * filled_size
                pnl = round(pnl, 4)

                self.state.settle_position(order_id, pnl=pnl, won=won)
                self.state.save(self.config.state_file)
                log_info(f"💰 结算完成: {pos.get('direction')} won={won} "
                         f"filled={filled_size} avg_price={avg_price} PnL=${pnl:+.4f}")
                if pnl < 0:
                    self.notifier.notify(
                        f"亏损 ${pnl:+.2f} | 累计今日 ${self.state.daily_pnl:+.2f}",
                        level='warn',
                    )
                if self.state.circuit_breaker:
                    self.notifier.notify("⛔ 熔断器已触发，请检查策略", level='error')
            except Exception as e:
                log_error(f"结算异常 {order_id}: {e}")

    def _market_won(self, slug: str, token_id: str, direction: str) -> Optional[bool]:
        """通过 Polymarket Gamma 接口判断该方向是否赢，兼容两种市场结构。"""
        try:
            event = self.client.get_btc_5m_market_by_slug(slug)
            if not event:
                return None
            markets = event.get('markets', []) or []

            # ---- 旧结构：两个子市场，按 groupItemTitle 匹配方向，YES=index 0 ----
            for m in markets:
                title = str(m.get('groupItemTitle', '')).upper()
                if not title or direction.upper() not in title:
                    continue
                prices = _coerce_list(m.get('outcomePrices'))
                if not prices:
                    return None
                try:
                    yes_price = float(prices[0])
                except (TypeError, ValueError):
                    return None
                return yes_price >= 0.99

            # ---- 新结构：单市场 + outcomes=["Up","Down"]，按 outcome 名匹配 ----
            for m in markets:
                outcomes = _coerce_list(m.get('outcomes'))
                prices = _coerce_list(m.get('outcomePrices'))
                if not outcomes or not prices:
                    continue
                for i, name in enumerate(outcomes):
                    if str(name).strip().upper() != direction.upper():
                        continue
                    if i >= len(prices):
                        return None
                    try:
                        side_price = float(prices[i])
                    except (TypeError, ValueError):
                        return None
                    return side_price >= 0.99
        except Exception as e:
            log_warn(f"_market_won 查询失败: {e}")
        return None


def main():
    try:
        config = Config()
        log_info(f"配置: strategy={config.strategy} dry_run={config.dry_run} "
                 f"trading_enabled={config.trading_enabled}")

        state = BotState.load(config.state_file)
        state.trading_enabled = config.trading_enabled

        client = PolymarketClient(config=config)
        feed = BinanceFeed()
        strategy = SniperStrategy(
            entry_secs=config.sniper_entry_secs,
            entry_window_low=config.sniper_entry_secs - 5,
            entry_window_high=config.sniper_entry_secs + 5,
            price_min=config.sniper_price_min,
            price_max=config.sniper_price_max,
            min_delta_bps=config.sniper_min_delta_bps,
            momentum_secs=config.sniper_momentum_secs,
            kelly_fraction=config.sniper_kelly_fraction,
        )
        notifier = Notifier(
            bot_token=config.telegram_bot_token,
            chat_id=config.telegram_chat_id,
        )

        bot = SniperBot(config=config, client=client, state=state,
                        feed=feed, strategy=strategy, notifier=notifier)

        asyncio.run(bot.run())

    except KeyboardInterrupt:
        log_info("⛔ 收到中断信号，正常退出")
        sys.exit(0)
    except Exception as e:
        log_error(f"❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
