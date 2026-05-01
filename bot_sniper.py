#!/usr/bin/env python3
"""
bot_sniper.py — 末端狙击机器人
策略：在BTC 5分钟窗口结束前约30秒入场，只在55%-60%份额价格区间买入，
结合Binance实时价格动量确认，使用半Kelly公式计算下注比例。
"""
import asyncio
import json
import logging
import sys
import time
from typing import List, Optional

from lib.config import Config
from lib.utils import log_info, log_error, log_warn
from lib.polymarket_client import PolymarketClient
from lib.bot_state import BotState
from lib.binance_feed import BinanceFeed
from lib.sniper_strategy import SniperStrategy

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# 每次轮询间隔（秒）
POLL_INTERVAL_SEC = 5


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


def _parse_outcome_prices(raw, default: Optional[List[float]] = None) -> List[float]:
    """
    解析 Polymarket Gamma API 返回的 outcomePrices。
    该字段可能是：
      - list: ["0.52", "0.48"] 或 [0.52, 0.48]
      - JSON 字符串: '["0.52","0.48"]'
      - None / 空 / 非法值
    任意元素无法转 float 时，回退为默认值。
    """
    if default is None:
        default = [0.5, 0.5]
    if raw is None:
        return list(default)
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return list(default)
    if not isinstance(raw, (list, tuple)) or not raw:
        return list(default)
    try:
        return [float(x) for x in raw]
    except (ValueError, TypeError):
        return list(default)


class SniperBot:
    """末端狙击机器人主控"""

    def __init__(self, config: Config, client: PolymarketClient,
                 state: BotState, feed: BinanceFeed, strategy: SniperStrategy):
        self.config = config
        self.client = client
        self.state = state
        self.feed = feed
        self.strategy = strategy

        # 每个窗口只允许入场1次
        self._last_entered_window_ts: Optional[int] = None

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

        while True:
            try:
                await self._cycle()
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
            # 读取UP/DOWN份额价格用于监控显示，失败时用N/A
            up_str = "N/A"
            down_str = "N/A"
            try:
                _markets = event.get('markets', [])
                _up_m = next((m for m in _markets if 'UP' in m.get('groupItemTitle', '').upper()), None)
                _down_m = next((m for m in _markets if 'DOWN' in m.get('groupItemTitle', '').upper()), None)
                if _up_m is None and _down_m is None and len(_markets) >= 2:
                    _up_m, _down_m = _markets[0], _markets[1]
                if _up_m:
                    _up_prices = _parse_outcome_prices(_up_m.get('outcomePrices'))
                    if _up_prices:
                        up_str = f"{_up_prices[0]:.3f}"
                if _down_m:
                    _down_prices = _parse_outcome_prices(_down_m.get('outcomePrices'))
                    if _down_prices:
                        down_str = f"{_down_prices[0]:.3f}"
            except Exception as e:
                log_warn(f"解析 outcomePrices 失败: {e}")
            log_info(f"⏳ 等待入场窗口 (剩余{remaining_seconds}s) | BTC={btc_price:.2f} | UP份额={up_str} DOWN份额={down_str}")
            return

        # 5. 检查该窗口是否已经入场过
        if self._last_entered_window_ts == window_open_ts:
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

        # 7. 解析市场价格
        markets = event.get('markets', [])
        active_markets = [m for m in markets
                          if m.get('acceptingOrders', False) and not m.get('closed', True)]
        if not active_markets:
            log_warn("⚠️  市场子单已关闭，跳过")
            return

        up_market = None
        down_market = None
        for m in active_markets:
            slug_lower = m.get('groupItemTitle', '').upper()
            if 'UP' in slug_lower:
                up_market = m
            elif 'DOWN' in slug_lower:
                down_market = m

        # 如果无法区分UP/DOWN，用前两个市场
        if up_market is None and len(active_markets) >= 2:
            up_market, down_market = active_markets[0], active_markets[1]
        elif up_market is None and len(active_markets) == 1:
            log_warn("只找到1个子市场，跳过本周期")
            return

        up_prices = _parse_outcome_prices(up_market.get('outcomePrices')) if up_market else [0.5, 0.5]
        down_prices = _parse_outcome_prices(down_market.get('outcomePrices')) if down_market else [0.5, 0.5]

        up_price = up_prices[0] if up_prices else 0.5
        down_price = down_prices[0] if down_prices else 0.5

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
        if not self.config.dry_run and self.config.trading_enabled:
            try:
                # 找到对应方向的token_id
                target_market = up_market if direction == 'UP' else down_market
                token_id = target_market.get('clobTokenIds', [''])[0] if target_market else ''
                if not token_id:
                    log_error(f"未找到 {direction} 方向的token_id，跳过")
                    return

                # py_clob_client 的 size 单位是「股数」（shares），不是 USDC。
                # shares = notional_USDC / price
                if entry_price <= 0:
                    log_error(f"非法 entry_price={entry_price}，跳过下单")
                    return
                shares = round(bet_size / entry_price, 2)

                self.client.place_order(
                    token_id=token_id,
                    side='buy',
                    price=entry_price,
                    size=shares,
                )
                log_info(
                    f"✅ 订单已提交: {direction} @ {entry_price:.3f} "
                    f"shares={shares:.2f} (~{bet_size:.2f} USDC)"
                )
            except Exception as e:
                log_error(f"下单失败: {e}")
                return
        else:
            log_info(f"🔬 DRY-RUN: {direction} @ {entry_price:.3f} x {bet_size:.2f} USDC（跳过真实下单）")

        # 12. 记录入场，防止本窗口重复入场
        self._last_entered_window_ts = window_open_ts
        self.state.record_trade(pnl=0.0)  # 真实盈亏在结算后更新
        self.state.save()
        log_info(f"💾 入场记录已保存 | 今日交易={self.state.daily_trade_count} "
                 f"今日PnL=${self.state.daily_pnl:.2f}")


def main():
    try:
        config = Config()
        log_info(f"配置: strategy={config.strategy} dry_run={config.dry_run} "
                 f"trading_enabled={config.trading_enabled}")

        state = BotState.load()
        state.trading_enabled = config.trading_enabled

        client = PolymarketClient(
            host=config.clob_host,
            chain_id=config.chain_id,
            private_key=config.private_key or None,
            funder=config.funder or None,
            signature_type=config.signature_type,
            api_key=config.clob_api_key or None,
            api_secret=config.clob_api_secret or None,
            api_passphrase=config.clob_api_passphrase or None,
        )

        # 实盘前自检：验证 PRIVATE_KEY / FUNDER / SIGNATURE_TYPE / API creds 组合
        if config.trading_enabled and not config.dry_run:
            try:
                status = client.get_wallet_status()
                log_info(f"🔐 钱包自检: {status}")
                if not status.get('ok'):
                    log_error(
                        "❌ 钱包/签名自检失败，请核对 SIGNATURE_TYPE 与 FUNDER："
                        " 0=EOA, 1=POLY_PROXY (FUNDER=Proxy地址),"
                        " 2=POLY_GNOSIS_SAFE (FUNDER=Safe地址)"
                    )
                    sys.exit(2)
            except Exception as e:
                log_error(f"❌ 无法初始化 CLOB 交易客户端: {e}")
                sys.exit(2)

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

        bot = SniperBot(config=config, client=client, state=state,
                        feed=feed, strategy=strategy)

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
