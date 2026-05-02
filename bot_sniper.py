#!/usr/bin/env python3
"""
bot_sniper.py — 末端狙击机器人
策略：在BTC 5分钟窗口结束前约30秒入场，只在55%-60%份额价格区间买入，
结合Binance实时价格动量确认，使用半Kelly公式计算下注比例。
"""
import asyncio
import json
import logging
import re
import sys
import time
from typing import Any, List, Optional, Tuple

from lib.config import Config
from lib.utils import log_info, log_error, log_warn
from lib.polymarket_client import PolymarketClient
from lib.polymarket_ws import PolymarketMarketWS
from lib.bot_state import BotState
from lib.binance_feed import BinanceFeed
from lib.sniper_strategy import SniperStrategy
from lib import trade_journal

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


def _parse_str_list(raw: Any) -> List[str]:
    """
    解析 Polymarket gamma API 中常以 JSON 字符串形式返回的字符串数组字段，
    例如 ``clobTokenIds`` / ``outcomes``。

    支持：
      - list/tuple: ["a", "b"]
      - JSON 字符串: '["a","b"]'
      - None / 空 / 非法值 → []
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return []
    if not isinstance(raw, (list, tuple)):
        return []
    return [str(x) for x in raw]


# 用于"整词匹配"的正则（避免 "UPDOWN" 误命中 "UP"）
_UP_TOKEN_RE = re.compile(r'\bUP\b')
_DOWN_TOKEN_RE = re.compile(r'\bDOWN\b')


def _market_label(m: dict) -> str:
    """把市场的多个标识字段拼成一个大写字符串，供关键字匹配。"""
    parts: List[str] = []
    for k in ('groupItemTitle', 'question', 'slug'):
        v = m.get(k)
        if isinstance(v, str) and v:
            parts.append(v)
    outcomes = _parse_str_list(m.get('outcomes'))
    parts.extend(outcomes)
    # slug 用 '-' 分隔；统一替换成空格以便整词匹配
    return ' '.join(parts).replace('-', ' ').upper()


def _classify_up_down(markets: List[dict]) -> Tuple[Optional[dict], Optional[dict]]:
    """
    在 event['markets'] 列表中识别 UP / DOWN 子市场。

    优先级：
      1. ``groupItemTitle`` 等价于 'UP' / 'DOWN'（最稳定的官方信号）
      2. ``question`` / ``slug`` / ``outcomes`` 中以整词形式包含 UP 或 DOWN，
         且不同时包含两个（避免事件级 "Up or Down" 文案误判）
      3. 仍未识别时按位置回退（前两个子市场依次作为 UP/DOWN）

    返回 (up_market, down_market)，单边缺失时仍尽量补齐。
    """
    up: Optional[dict] = None
    down: Optional[dict] = None

    # 1. groupItemTitle 精确匹配
    for m in markets:
        title = (m.get('groupItemTitle') or '').strip().upper()
        if title == 'UP' and up is None:
            up = m
        elif title == 'DOWN' and down is None:
            down = m

    # 2. 多字段整词关键字匹配
    if up is None or down is None:
        for m in markets:
            if m is up or m is down:
                continue
            label = _market_label(m)
            has_up = bool(_UP_TOKEN_RE.search(label))
            has_down = bool(_DOWN_TOKEN_RE.search(label))
            # 同时包含 UP 和 DOWN 的市场（如事件级文案 "Up or Down"）不参与判定
            if has_up and not has_down and up is None:
                up = m
            elif has_down and not has_up and down is None:
                down = m

    # 3. 位置回退：补齐单边缺失，或双缺失时取前两个
    if up is None and down is None and len(markets) >= 2:
        return markets[0], markets[1]
    if up is None and down is not None:
        rest = [m for m in markets if m is not down]
        if rest:
            up = rest[0]
    elif down is None and up is not None:
        rest = [m for m in markets if m is not up]
        if rest:
            down = rest[0]

    return up, down


def _coerce_float(raw: Any) -> Optional[float]:
    """尽力把字符串/数字转 float；非法值返回 None。"""
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (ValueError, TypeError):
        return None


def _extract_yes_price(market: Optional[dict]) -> Optional[float]:
    """
    从一个子市场提取「YES」侧（UP/DOWN 子市场的多头）的最佳可用价格。
    Gamma API 的不同响应中价格字段并不一致，按可信度依次回退：
      1. outcomePrices[0]（事件聚合接口中最常见）
      2. lastTradePrice（最近成交价）
      3. (bestBid + bestAsk) / 2 中位（双边都存在时）
      4. bestBid / bestAsk（仅单边）
    全部缺失时返回 None，调用方可显示占位符。
    """
    if not isinstance(market, dict):
        return None
    prices = _parse_outcome_prices(market.get('outcomePrices'), default=[])
    if prices:
        return prices[0]
    last = _coerce_float(market.get('lastTradePrice'))
    if last is not None:
        return last
    bid = _coerce_float(market.get('bestBid'))
    ask = _coerce_float(market.get('bestAsk'))
    if bid is not None and ask is not None:
        return (bid + ask) / 2
    return bid if bid is not None else ask


def _market_summary_for_log(m: dict) -> dict:
    """提取一个子市场的关键标识字段供 diagnostic 日志使用（控制体积）。"""
    return {
        'groupItemTitle': m.get('groupItemTitle'),
        'question': (m.get('question') or '')[:120],
        'slug': m.get('slug'),
        'outcomes': _parse_str_list(m.get('outcomes')),
        'has_outcomePrices': m.get('outcomePrices') is not None,
        'acceptingOrders': m.get('acceptingOrders'),
        'closed': m.get('closed'),
    }


class SniperBot:
    """末端狙击机器人主控"""

    def __init__(self, config: Config, client: PolymarketClient,
                 state: BotState, feed: BinanceFeed, strategy: SniperStrategy,
                 market_ws: Optional[PolymarketMarketWS] = None):
        self.config = config
        self.client = client
        self.state = state
        self.feed = feed
        self.strategy = strategy
        self.market_ws = market_ws

        # 每个窗口只允许入场1次（重启后从持久化 state 恢复，避免重复下单）
        self._last_entered_window_ts: Optional[int] = state.last_entered_window_ts
        # 仅在第一次回退到位置识别时打印一次结构 diagnostic
        self._diagnostic_logged: bool = False
        # 上一次推送给 WS 的 (up_token, down_token) 组合，用于检测窗口翻页
        self._ws_active_pair: Tuple[Optional[str], Optional[str]] = (None, None)
        # 距离上一次余额预检冷却（避免每个周期都打 RPC）
        self._last_preflight_ts: float = 0.0
        self._last_preflight_result: Optional[dict] = None

    def _fetch_yes_price_via_orderbook(self, market: Optional[dict]) -> Optional[float]:
        """
        从 Polymarket CLOB orderbook 获取该子市场 YES 侧的中间价。

        优先级：
          1. ``PolymarketMarketWS`` 实时缓存（订阅了对应 token 时秒级新鲜）
          2. REST ``get_orderbook`` + ``calculate_mid_price``
          3. gamma 字段（``outcomePrices`` / ``lastTradePrice`` / ``bestBid`` 等）

        前两者都失败时回到 ``_extract_yes_price``，再失败返回 ``None`` 由调用方
        显示占位符。
        """
        if not isinstance(market, dict):
            return None
        token_ids = _parse_str_list(market.get('clobTokenIds'))
        token_id = token_ids[0] if token_ids else ''
        if token_id and self.market_ws is not None:
            try:
                mid = self.market_ws.get_mid(token_id)
                if mid is not None:
                    return float(mid)
            except Exception as e:  # pragma: no cover - defensive
                log_warn(f"WS 取价异常，回退到 REST: {e}")
        if token_id:
            try:
                book = self.client.get_orderbook(token_id)
                pricing = self.client.calculate_mid_price(book)
                mid = pricing.get('mid') if isinstance(pricing, dict) else None
                if mid is not None:
                    return float(mid)
            except Exception as e:
                log_warn(f"orderbook 取价失败，回退到 outcomePrices: {e}")
        return _extract_yes_price(market)

    def _update_ws_subscriptions(self, up_market: Optional[dict],
                                 down_market: Optional[dict]) -> None:
        """根据当前窗口的 UP/DOWN 子市场更新 WS 订阅集合。

        只有 token 组合发生变化（典型：5m 窗口翻页）才会触发 ``set_active_tokens``，
        避免每个轮询周期都重连。
        """
        if self.market_ws is None:
            return
        up_tid = ''
        down_tid = ''
        if isinstance(up_market, dict):
            tids = _parse_str_list(up_market.get('clobTokenIds'))
            up_tid = tids[0] if tids else ''
        if isinstance(down_market, dict):
            tids = _parse_str_list(down_market.get('clobTokenIds'))
            down_tid = tids[0] if tids else ''
        new_pair = (up_tid or None, down_tid or None)
        if new_pair == self._ws_active_pair:
            return
        tokens = [t for t in (up_tid, down_tid) if t]
        try:
            self.market_ws.set_active_tokens(tokens)
            self._ws_active_pair = new_pair
            if tokens:
                log_info(
                    f"📡 WS 订阅切换: UP={up_tid[:12] + '…' if up_tid else 'N/A'} "
                    f"DOWN={down_tid[:12] + '…' if down_tid else 'N/A'}"
                )
        except Exception as e:  # pragma: no cover - defensive
            log_warn(f"更新 WS 订阅失败: {e}")


    def _log_market_diagnostic(self, event: dict, reason: str) -> None:
        """无法用关键字识别 UP/DOWN 时打印一次市场结构，便于排查字段差异。"""
        if self._diagnostic_logged:
            return
        self._diagnostic_logged = True
        try:
            ms = event.get('markets', []) or []
            samples = [_market_summary_for_log(m) for m in ms[:2]]
            log_warn(
                f"🔎 market diagnostic ({reason}): "
                f"event.slug={event.get('slug')} markets={len(ms)} "
                f"samples={samples}"
            )
        except Exception as e:  # pragma: no cover - defensive
            log_warn(f"market diagnostic 打印失败: {e}")

    # ----------------------------------------------------------------- preflight
    def _preflight_balance(self, notional_usdc: float) -> Tuple[bool, str, dict]:
        """检查 USDC 余额与 CLOB approval 是否足以下这笔单。

        DRY_RUN 或 TRADING_ENABLED=false 时直接放行（返回 ok=True），让监控
        模式不被这一项卡住。失败时返回 (False, 原因) 由调用方决定告警/跳过。
        """
        if self.config.dry_run or not self.config.trading_enabled:
            return True, "dry-run", {}
        try:
            res = self.client.get_usdc_balance_allowance()
        except Exception as e:
            return False, f"balance/allowance 查询异常: {e}", {}
        if not res.get("ok"):
            return False, f"balance/allowance 不可用: {res.get('error', 'unknown')}", res
        bal = float(res.get("balance_usdc", 0.0))
        allow = float(res.get("allowance_usdc", 0.0))
        # 留 5% 缓冲，避免 fee/滑点导致刚好不够
        required = notional_usdc * 1.05
        if bal < required:
            return (
                False,
                f"USDC 余额不足: {bal:.2f} < 需要 {required:.2f} (含5%缓冲)",
                res,
            )
        if allow < required:
            return (
                False,
                f"USDC approval 不足: {allow:.2f} < 需要 {required:.2f}；"
                f"请到 Polymarket 网站完成 USDC approval",
                res,
            )
        return True, f"OK (balance={bal:.2f} allowance={allow:.2f})", res

    # ------------------------------------------------------------ settlement
    def _settle_pending_entry(self, now: int) -> None:
        """如果存在待结算的 pending_entry，且其窗口已结束，则结算。

        步骤：
          1. 查 gamma 拿到该 slug 的最终 outcomePrices（赢=1，输=0）。
          2. 查 CLOB get_trades 拿到我们这边实际成交的份数与均价。
          3. 计算实盘 PnL：未成交的部分 PnL=0，成交部分按结果赔付。
          4. 把真实 PnL 通过 record_trade 写入 daily_pnl 风控。
          5. 写一行 settle 到 trades.jsonl 用于复盘。
          6. 同时尝试撤掉残留的未成交订单（窗口结束后死单，占用保证金）。
        """
        pe = self.state.pending_entry
        if not pe or pe.get("settled"):
            return
        end_ts = int(pe.get("window_end_ts") or 0)
        if end_ts <= 0 or now < end_ts:
            return  # 窗口还没结束

        slug = pe.get("slug") or ""
        token_id = pe.get("token_id") or ""
        condition_id = pe.get("condition_id") or None
        direction = pe.get("direction") or "UP"
        entry_price = float(pe.get("entry_price") or 0.0)
        shares_req = float(pe.get("shares_requested") or 0.0)
        order_id = pe.get("order_id") or None
        attempts = int(pe.get("settle_attempts") or 0) + 1
        pe["settle_attempts"] = attempts

        # 1) 撤掉任何残留的未成交订单（避免窗口已结束还有死单）
        if order_id and self.config.trading_enabled and not self.config.dry_run:
            try:
                opens = self.client.get_open_orders(asset_id=token_id)
                still_open_ids = [
                    o.get("id") for o in opens
                    if isinstance(o, dict) and o.get("id") == order_id
                ]
                if still_open_ids:
                    cancel_resp = self.client.cancel_orders(still_open_ids)
                    log_info(
                        f"🧹 已撤未成交订单: order_id={order_id[:12]}… resp={cancel_resp}"
                    )
                    trade_journal.append("cancel", {
                        "slug": slug,
                        "order_id": order_id,
                        "response": cancel_resp,
                    })
            except Exception as e:
                log_warn(f"撤单异常（不影响结算）: {e}")

        # 2) 查 gamma 拿到最终赔付价（outcomePrices）
        outcome_payout: Optional[float] = None
        market_resolved = False
        try:
            event = self.client.get_btc_5m_market_by_slug(slug) if slug else None
            if event:
                up_m, down_m = _classify_up_down(event.get("markets", []) or [])
                target = up_m if direction == "UP" else down_m
                if isinstance(target, dict):
                    prices = _parse_outcome_prices(target.get("outcomePrices"), default=[])
                    closed = bool(target.get("closed", False))
                    # 已结算：outcomePrices 非空且为 0/1 二元
                    if closed and prices:
                        outcome_payout = float(prices[0])
                        market_resolved = True
        except Exception as e:
            log_warn(f"查询 gamma 结算价失败: {e}")

        # 3) 查实际成交（拿到真正的 filled shares 与均价）
        filled_shares = 0.0
        avg_fill_price = entry_price
        try:
            if self.config.trading_enabled and not self.config.dry_run:
                submit_ts = int(pe.get("submit_ts") or end_ts - 60)
                trades = self.client.get_trades_for_market(
                    market=condition_id,
                    asset_id=token_id,
                    after=max(submit_ts - 5, 0),
                )
                tot_shares = 0.0
                tot_notional = 0.0
                for t in trades:
                    try:
                        sz = float(t.get("size", 0))
                        pr = float(t.get("price", 0))
                        side = str(t.get("side", "")).upper()
                        if side and side != "BUY":
                            continue
                        tot_shares += sz
                        tot_notional += sz * pr
                    except (TypeError, ValueError):
                        continue
                if tot_shares > 0:
                    filled_shares = tot_shares
                    avg_fill_price = tot_notional / tot_shares
            else:
                # DRY_RUN：把请求的 shares 当成全部成交，仅用于 PnL 演练
                filled_shares = shares_req
        except Exception as e:
            log_warn(f"查询成交失败: {e}")

        # 4) 决定是否可以结算
        # 如果市场还没 resolve，但已经多次尝试且距窗口结束 > 10 分钟，按 0 PnL 收尾
        # （仍保留 pending 中的真实成交记录给复盘）。
        STALE_AFTER_SEC = 10 * 60
        give_up = (now - end_ts) > STALE_AFTER_SEC and attempts >= 3
        if not market_resolved and not give_up and outcome_payout is None:
            log_info(
                f"⏳ 等待 gamma 结算（slug={slug} attempt={attempts}），下个周期再试"
            )
            self.state.save()
            return

        # 5) 计算实盘 PnL
        if outcome_payout is None:
            outcome_payout = 0.0  # 放弃模式：保守按 0 计
        # PnL = filled_shares * (payout - avg_fill_price)
        realized_pnl = round(filled_shares * (outcome_payout - avg_fill_price), 4)

        log_info(
            f"💼 结算 {slug} dir={direction} filled={filled_shares:.2f} @ "
            f"{avg_fill_price:.3f} payout={outcome_payout:.2f} → PnL={realized_pnl:+.3f} USDC"
        )

        # 6) 写入风控（如果完全没成交则不计入 trade count，避免污染连亏统计）
        if filled_shares > 0:
            self.state.record_trade(pnl=realized_pnl)

        trade_journal.append("settle", {
            "slug": slug,
            "direction": direction,
            "entry_price": entry_price,
            "shares_requested": shares_req,
            "filled_shares": filled_shares,
            "avg_fill_price": avg_fill_price,
            "outcome_payout": outcome_payout,
            "realized_pnl": realized_pnl,
            "market_resolved": market_resolved,
            "gave_up": give_up,
            "order_id": order_id,
        })

        pe["settled"] = True
        pe["realized_pnl"] = realized_pnl
        pe["filled_shares"] = filled_shares
        pe["avg_fill_price"] = avg_fill_price
        pe["outcome_payout"] = outcome_payout
        # 已结算后清空 pending（保留最近一条到 closed_positions 备查）
        self.state.closed_positions.append(pe)
        # 仅保留最近 50 条避免文件无限增长
        self.state.closed_positions = self.state.closed_positions[-50:]
        self.state.pending_entry = None
        self.state.save()

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

        # 在同一个 event loop 中启动 Polymarket 实时行情 WS 任务
        ws_task: Optional[asyncio.Task] = None
        if self.market_ws is not None:
            ws_task = asyncio.create_task(self.market_ws.run(),
                                          name="polymarket-market-ws")
            log_info("📡 Polymarket 行情 WS 任务已启动")

        try:
            while True:
                try:
                    await self._cycle()
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    log_error(f"周期异常（已捕获，继续运行）: {e}")
                await asyncio.sleep(POLL_INTERVAL_SEC)
        finally:
            if self.market_ws is not None:
                self.market_ws.stop()
            if ws_task is not None:
                ws_task.cancel()
                try:
                    await ws_task
                except (asyncio.CancelledError, Exception):
                    pass

    async def _cycle(self):
        """单次周期"""
        now = int(time.time())

        # 0. 优先尝试结算上一窗口未结算的 pending_entry（不阻塞主流程）
        try:
            self._settle_pending_entry(now)
        except Exception as e:
            log_warn(f"结算异常（忽略，下周期重试）: {e}")

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

        # 3.5 在做任何价格读取前，先把当前窗口的 UP/DOWN token 推送给 WS 订阅
        # （首次出现 / 窗口翻页时会触发重连，让 ``get_mid`` 立刻收到 book 快照）。
        try:
            _all_markets = event.get('markets', []) or []
            _up_pre, _down_pre = _classify_up_down(_all_markets)
            self._update_ws_subscriptions(_up_pre, _down_pre)
        except Exception as e:  # pragma: no cover - defensive
            log_warn(f"准备 WS 订阅失败: {e}")

        # 4. 如果剩余 > entry_window_high + 5s：仅记录价格，等待入场窗口
        if remaining_seconds > self.strategy.entry_window_high + 5:
            # 读取UP/DOWN份额价格用于监控显示，失败时用N/A
            up_str = "N/A"
            down_str = "N/A"
            try:
                _markets = event.get('markets', []) or []
                _up_m, _down_m = _classify_up_down(_markets)
                if _up_m is None or _down_m is None:
                    self._log_market_diagnostic(
                        event,
                        reason=f"classify partial: up={_up_m is not None} down={_down_m is not None}",
                    )
                _up_p = self._fetch_yes_price_via_orderbook(_up_m)
                if _up_p is not None:
                    up_str = f"{_up_p:.3f}"
                _down_p = self._fetch_yes_price_via_orderbook(_down_m)
                if _down_p is not None:
                    down_str = f"{_down_p:.3f}"
            except Exception as e:
                log_warn(f"解析份额价格失败: {e}")
            log_info(f"⏳ 等待入场窗口 (剩余{remaining_seconds}s) | BTC={btc_price:.2f} | UP份额={up_str} DOWN份额={down_str}")
            return

        # 5. 检查该窗口是否已经入场过
        if self._last_entered_window_ts == window_open_ts:
            log_info(f"✅ 本窗口已入场，等待下一窗口")
            return

        # 6. 检查风控
        can, reason = self.state.can_trade(
            daily_loss_limit=self.config.daily_loss_limit_usdc,
            consec_loss_limit=self.config.consecutive_loss_limit,
        )
        if not can:
            log_warn(f"⏸ 交易暂停: {reason}")
            return

        # 7. 解析市场价格
        markets = event.get('markets', []) or []
        active_markets = [m for m in markets
                          if m.get('acceptingOrders', False) and not m.get('closed', True)]
        if not active_markets:
            log_warn("⚠️  市场子单已关闭，跳过")
            return

        up_market, down_market = _classify_up_down(active_markets)
        if up_market is None or down_market is None:
            self._log_market_diagnostic(
                event,
                reason=f"trade-path classify partial: up={up_market is not None} down={down_market is not None}",
            )
        if up_market is None:
            log_warn("无法识别 UP 子市场，跳过本周期")
            return

        up_price_ob = self._fetch_yes_price_via_orderbook(up_market)
        down_price_ob = (
            self._fetch_yes_price_via_orderbook(down_market)
            if down_market else None
        )

        up_price = up_price_ob if up_price_ob is not None else 0.5
        down_price = down_price_ob if down_price_ob is not None else 0.5

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

        # 11. 解析目标 token / condition / shares（实盘 & DRY_RUN 都需要）
        target_market = up_market if direction == 'UP' else down_market
        if target_market is None:
            log_error(f"未找到 {direction} 方向的子市场，跳过")
            return
        token_ids = _parse_str_list(target_market.get('clobTokenIds'))
        token_id = token_ids[0] if token_ids else ''
        if not token_id:
            log_error(f"未找到 {direction} 方向的token_id，跳过")
            return
        if entry_price <= 0:
            log_error(f"非法 entry_price={entry_price}，跳过下单")
            return
        # py_clob_client 的 size 单位是「股数」(shares)，不是 USDC。
        shares = round(bet_size / entry_price, 2)
        condition_id = target_market.get('conditionId') or target_market.get('condition_id') or None

        # 11.1 下单前余额/授权预检（仅实盘路径执行）
        ok_pre, pre_reason, _pre_raw = self._preflight_balance(bet_size)
        if not ok_pre:
            log_error(f"⛔ 下单预检不通过，跳过本窗口: {pre_reason}")
            return
        log_info(f"🔍 余额预检: {pre_reason}")

        # 11.2 执行下单
        order_resp: dict = {}
        order_id: Optional[str] = None
        if not self.config.dry_run and self.config.trading_enabled:
            try:
                order_resp = self.client.place_order(
                    token_id=token_id,
                    side='buy',
                    price=entry_price,
                    size=shares,
                ) or {}
                order_id = order_resp.get('orderID') or order_resp.get('order_id') or None
                log_info(
                    f"✅ 订单已提交: {direction} @ {entry_price:.3f} "
                    f"shares={shares:.2f} (~{bet_size:.2f} USDC) order_id={order_id}"
                )
            except Exception as e:
                log_error(f"下单失败: {e}")
                trade_journal.append("submit_error", {
                    "slug": event.get('slug'),
                    "direction": direction,
                    "entry_price": entry_price,
                    "shares": shares,
                    "notional_usdc": bet_size,
                    "error": str(e),
                })
                return
        else:
            log_info(f"🔬 DRY-RUN: {direction} @ {entry_price:.3f} x {bet_size:.2f} USDC（跳过真实下单）")

        # 11.3 写入 JSONL 提交日志（DRY_RUN 也写，便于复盘策略行为）
        trade_journal.append("submit", {
            "slug": event.get('slug'),
            "window_open_ts": window_open_ts,
            "window_end_ts": window_end_ts,
            "direction": direction,
            "entry_price": entry_price,
            "shares": shares,
            "notional_usdc": bet_size,
            "edge": edge,
            "estimated_prob": estimated_prob,
            "kelly_fraction": kelly,
            "token_id": token_id,
            "condition_id": condition_id,
            "order_id": order_id,
            "order_response": order_resp,
            "dry_run": bool(self.config.dry_run),
        })

        # 12. 记录入场（持久化），防止本窗口重复入场 + 让重启能继续结算
        self._last_entered_window_ts = window_open_ts
        self.state.last_entered_window_ts = window_open_ts
        self.state.pending_entry = {
            "slug": event.get('slug'),
            "window_open_ts": window_open_ts,
            "window_end_ts": window_end_ts,
            "direction": direction,
            "token_id": token_id,
            "condition_id": condition_id,
            "entry_price": entry_price,
            "shares_requested": shares,
            "notional_usdc": bet_size,
            "order_id": order_id,
            "order_response": order_resp,
            "submit_ts": int(time.time()),
            "dry_run": bool(self.config.dry_run),
            "settled": False,
            "settle_attempts": 0,
        }
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

        market_ws = PolymarketMarketWS()

        bot = SniperBot(config=config, client=client, state=state,
                        feed=feed, strategy=strategy, market_ws=market_ws)

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
