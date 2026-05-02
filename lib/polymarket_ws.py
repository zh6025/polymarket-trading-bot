"""
PolymarketMarketWS — Polymarket CLOB 实时行情 WebSocket 客户端

订阅指定 ``asset_id``（即 ``clobTokenIds`` 中的 token id）的实时订单簿，
维护本地 bids/asks 缓存，对外提供 ``get_mid(token_id)`` 等同步只读接口
供策略代码即时读取。

设计要点：
* 端点：``wss://ws-subscriptions-clob.polymarket.com/ws/market``
* 订阅消息：``{"assets_ids": [...], "type": "market"}``
* 消息类型（参考 Polymarket 公开文档）：
    - 列表（[ {asset_id, bids, asks, ...}, ... ]）：连接后的初始全量快照
    - dict 含 ``bids/asks``：单个标的的全量快照
    - dict 含 ``price_changes``（也可能为 ``changes``）：增量价位更新
* 支持运行中追加 / 替换订阅集合；替换时强制重连以避免服务端继续推送
  已结算窗口的旧 token。
* 自动重连：网络异常 / 连接关闭后短暂回退后重新建立连接，重新订阅当
  前 ``_active_tokens`` 集合，对调用方透明。
* 整体只在自身的 asyncio 任务内运行，不阻塞策略主循环；策略主循环
  通过 ``get_mid`` / ``get_book`` 同步读取已缓存的最新价格。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

try:
    import websockets
    from websockets.exceptions import ConnectionClosed
    _WS_AVAILABLE = True
except ImportError:  # pragma: no cover - import guard
    websockets = None  # type: ignore
    ConnectionClosed = Exception  # type: ignore
    _WS_AVAILABLE = False


CLOB_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

# 缓存的价格在多长时间内仍被视为「实时」。超出该阈值则 ``get_mid`` 返
# 回 ``None`` 让调用方回退到 REST 查询。
DEFAULT_FRESHNESS_SEC = 30.0

# 重连退避（秒）。指数退避到上限后保持。
_RECONNECT_BACKOFF_INITIAL = 1.0
_RECONNECT_BACKOFF_MAX = 30.0

logger = logging.getLogger(__name__)


def _coerce_float(raw: Any) -> Optional[float]:
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _parse_levels(raw: Any) -> List[Tuple[float, float]]:
    """把 ``[{"price": "0.5", "size": "10"}, ...]`` 解析为 ``[(price, size), ...]``。

    其他形态（``None`` / 非列表 / 缺字段）一律视为空。
    """
    if not isinstance(raw, list):
        return []
    out: List[Tuple[float, float]] = []
    for lvl in raw:
        if not isinstance(lvl, dict):
            continue
        p = _coerce_float(lvl.get("price"))
        s = _coerce_float(lvl.get("size"))
        if p is None or s is None:
            continue
        out.append((p, s))
    return out


class _BookState:
    """单个 ``asset_id`` 的本地订单簿缓存（仅 top levels）。"""

    __slots__ = ("asset_id", "bids", "asks", "last_update_ts")

    def __init__(self, asset_id: str):
        self.asset_id: str = asset_id
        # 按价格降序存 bids（最高买在前），升序存 asks（最低卖在前）。
        self.bids: List[Tuple[float, float]] = []
        self.asks: List[Tuple[float, float]] = []
        # 单调时钟时间戳，用于判断「实时性」。0 表示尚未收到任何快照。
        self.last_update_ts: float = 0.0

    # ---------------- snapshot ------------------------------------------

    def apply_snapshot(self, bids: Iterable[Tuple[float, float]],
                       asks: Iterable[Tuple[float, float]]) -> None:
        # 过滤 size==0 的占位档位，再按价格排序。
        b = [(p, s) for (p, s) in bids if s > 0]
        a = [(p, s) for (p, s) in asks if s > 0]
        b.sort(key=lambda x: x[0], reverse=True)
        a.sort(key=lambda x: x[0])
        self.bids = b[:20]
        self.asks = a[:20]
        self.last_update_ts = time.monotonic()

    # ---------------- incremental --------------------------------------

    @staticmethod
    def _apply_level(levels: List[Tuple[float, float]], price: float,
                     size: float, *, descending: bool) -> List[Tuple[float, float]]:
        """在排序好的列表里 upsert 一个 ``(price, size)``；``size==0`` 表示删除。"""
        # 先剔除同价位的旧档位
        out = [lvl for lvl in levels if lvl[0] != price]
        if size > 0:
            out.append((price, size))
        out.sort(key=lambda x: x[0], reverse=descending)
        return out[:20]

    def apply_change(self, price: Optional[float], size: Optional[float],
                     side: Optional[str]) -> None:
        if price is None or size is None or side is None:
            return
        side_norm = str(side).strip().upper()
        # Polymarket 在 price_change 里通常用 BUY/SELL，少数响应里用 bid/ask；
        # 这里两者都兼容。
        if side_norm in ("BUY", "BID", "B"):
            self.bids = self._apply_level(self.bids, price, size, descending=True)
        elif side_norm in ("SELL", "ASK", "A"):
            self.asks = self._apply_level(self.asks, price, size, descending=False)
        else:
            return
        self.last_update_ts = time.monotonic()

    # ---------------- read ---------------------------------------------

    def best_bid(self) -> Optional[float]:
        return self.bids[0][0] if self.bids else None

    def best_ask(self) -> Optional[float]:
        return self.asks[0][0] if self.asks else None

    def mid(self) -> Optional[float]:
        bb, ba = self.best_bid(), self.best_ask()
        if bb is not None and ba is not None:
            return (bb + ba) / 2.0
        return bb if bb is not None else ba

    def is_fresh(self, max_age_sec: float) -> bool:
        if self.last_update_ts <= 0.0:
            return False
        return (time.monotonic() - self.last_update_ts) <= max_age_sec


class PolymarketMarketWS:
    """Polymarket CLOB 行情订阅器（asyncio）。

    典型用法（在 asyncio 循环里）::

        ws = PolymarketMarketWS()
        asyncio.create_task(ws.run())
        ws.set_active_tokens([up_token_id, down_token_id])
        ...
        mid = ws.get_mid(up_token_id)
    """

    def __init__(
        self,
        url: str = CLOB_WS_URL,
        freshness_sec: float = DEFAULT_FRESHNESS_SEC,
    ):
        self.url = url
        self.freshness_sec = float(freshness_sec)

        # 当前应订阅的全量 token 集合（替换性集合）。
        self._active_tokens: Set[str] = set()
        # 等待在已建立的连接上追加订阅的 token（增量）。
        self._pending_subs: Set[str] = set()
        # 本地订单簿缓存：token_id -> _BookState
        self._books: Dict[str, _BookState] = {}

        # 控制后台循环的异步事件
        self._stop_event = asyncio.Event()
        # 触发当前连接立刻断开重连（用于切换窗口时清理旧订阅）。
        self._reconnect_event = asyncio.Event()
        # 通知 run 循环有新的 pending 订阅可发送。
        self._wake_event = asyncio.Event()

        # 标记后台任务是否在运行（仅用于诊断日志，避免重复启动）。
        self._running: bool = False

    # ------------------------------------------------------------------
    # 公开同步接口（供主循环 / 策略模块调用）
    # ------------------------------------------------------------------

    def set_active_tokens(self, token_ids: Iterable[str]) -> None:
        """替换当前的订阅集合。

        当窗口翻页（出现新的 5m 市场）时调用：会清掉不在新集合里的本地缓存，
        并触发 WS 重连，确保服务器不再继续推送已经过期的 token。
        """
        new_set = {str(t) for t in token_ids if t}
        if new_set == self._active_tokens:
            return
        added = new_set - self._active_tokens
        removed = self._active_tokens - new_set
        self._active_tokens = new_set
        # 清掉已经不再订阅的本地簿，避免 ``get_mid`` 返回过期数据
        for t in removed:
            self._books.pop(t, None)
        # 任何 add 都需要 server 端重新认知；最简单做法 = 重连
        if added or removed:
            logger.info(
                "PolymarketWS active tokens 更新: +%d / -%d (total=%d)",
                len(added), len(removed), len(new_set),
            )
            self._reconnect_event.set()
            self._wake_event.set()

    def add_tokens(self, token_ids: Iterable[str]) -> None:
        """在不影响其它订阅的前提下追加 token（增量订阅）。"""
        new_tokens = {str(t) for t in token_ids if t} - self._active_tokens
        if not new_tokens:
            return
        self._active_tokens.update(new_tokens)
        self._pending_subs.update(new_tokens)
        self._wake_event.set()

    def get_mid(self, token_id: str) -> Optional[float]:
        """返回该 token 当前的中间价（``(best_bid + best_ask) / 2``）。

        如果尚未收到任何更新、或最近一次更新已超过 ``freshness_sec``，返回
        ``None`` 让调用方回退到 REST 查询。
        """
        b = self._books.get(str(token_id))
        if b is None or not b.is_fresh(self.freshness_sec):
            return None
        return b.mid()

    def get_book_summary(self, token_id: str) -> Optional[Dict[str, Any]]:
        """诊断用：返回 ``{best_bid, best_ask, mid, age_sec}``。"""
        b = self._books.get(str(token_id))
        if b is None or b.last_update_ts <= 0.0:
            return None
        return {
            "best_bid": b.best_bid(),
            "best_ask": b.best_ask(),
            "mid": b.mid(),
            "age_sec": time.monotonic() - b.last_update_ts,
        }

    def stop(self) -> None:
        """请求后台任务退出。"""
        self._stop_event.set()
        self._wake_event.set()
        self._reconnect_event.set()

    # ------------------------------------------------------------------
    # 后台主循环（asyncio task）
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """连接 / 重连主循环。需要由调用方放进 asyncio.create_task。"""
        if not _WS_AVAILABLE:
            logger.warning(
                "websockets 包未安装，PolymarketMarketWS 不会启动；"
                "运行 `pip install websockets` 以启用实时行情。"
            )
            return
        if self._running:
            logger.warning("PolymarketMarketWS.run 已经在运行，忽略重复调用")
            return
        self._running = True
        backoff = _RECONNECT_BACKOFF_INITIAL
        try:
            while not self._stop_event.is_set():
                # 没有任何订阅时，等待外部 set_active_tokens / add_tokens
                if not self._active_tokens:
                    self._wake_event.clear()
                    try:
                        await asyncio.wait_for(self._wake_event.wait(), timeout=1.0)
                    except asyncio.TimeoutError:
                        pass
                    continue

                self._reconnect_event.clear()
                try:
                    await self._connect_and_run()
                    # 正常返回：通常意味着外部触发了重连（切窗口）。
                    backoff = _RECONNECT_BACKOFF_INITIAL
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # pragma: no cover - network is flaky
                    logger.warning(
                        "PolymarketWS 连接异常: %s — %.1fs 后重连", e, backoff,
                    )
                    try:
                        await asyncio.wait_for(self._stop_event.wait(), timeout=backoff)
                        # stop_event set -> 退出
                        break
                    except asyncio.TimeoutError:
                        pass
                    backoff = min(backoff * 2.0, _RECONNECT_BACKOFF_MAX)
        finally:
            self._running = False

    async def _connect_and_run(self) -> None:
        """单次连接生命周期：建立 → 订阅 → 接收循环。"""
        assert _WS_AVAILABLE
        logger.info("连接 Polymarket WSS: %s (assets=%d)",
                    self.url, len(self._active_tokens))
        async with websockets.connect(
            self.url,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=5,
            max_size=8 * 1024 * 1024,
        ) as ws:
            # 初次发送全量订阅
            initial_tokens = list(self._active_tokens)
            self._pending_subs.clear()
            await ws.send(json.dumps({
                "assets_ids": initial_tokens,
                "type": "market",
            }))
            logger.info("PolymarketWS 已订阅 %d 个 token", len(initial_tokens))

            # 接收循环
            while not self._stop_event.is_set() and not self._reconnect_event.is_set():
                # 优先处理增量订阅
                if self._pending_subs:
                    new_tokens = list(self._pending_subs)
                    self._pending_subs.clear()
                    try:
                        await ws.send(json.dumps({
                            "assets_ids": new_tokens,
                            "type": "market",
                        }))
                        logger.info("PolymarketWS 增量订阅 %d 个 token", len(new_tokens))
                    except Exception as e:
                        logger.warning("增量订阅发送失败: %s", e)
                        # 让外层重连
                        break

                # 短超时 recv，便于及时响应 reconnect / pending_subs
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                except ConnectionClosed:
                    logger.info("PolymarketWS 服务端关闭连接，准备重连")
                    return

                self._handle_message(raw)

    # ------------------------------------------------------------------
    # 消息处理（同步，便于在测试中直接调用）
    # ------------------------------------------------------------------

    def _handle_message(self, raw: Any) -> None:
        """解析一条原始消息（``str``/``bytes``/已 parse 好的 dict 或 list）。"""
        try:
            if isinstance(raw, (bytes, bytearray)):
                raw = raw.decode("utf-8", errors="replace")
            if isinstance(raw, str):
                if not raw.strip():
                    return
                if raw.strip() in ("PONG", "PING"):
                    # 服务端心跳，无需处理
                    return
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    return
            else:
                data = raw
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("WS 消息解析失败: %s", e)
            return

        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    self._dispatch(item)
        elif isinstance(data, dict):
            self._dispatch(data)

    def _dispatch(self, msg: Dict[str, Any]) -> None:
        # 不同 schema 的兼容判别：
        #   - 全量 book：顶层包含 ``bids`` 或 ``asks``
        #   - price_change：顶层包含 ``price_changes`` 或 ``changes``
        #   - 其它（如 ``last_trade_price`` / ``tick_size_change``）忽略
        event_type = msg.get("event_type") or msg.get("type")

        if "bids" in msg or "asks" in msg or event_type == "book":
            self._apply_book(msg)
            return

        changes = msg.get("price_changes")
        if changes is None:
            changes = msg.get("changes")
        if changes is not None or event_type == "price_change":
            self._apply_price_change(msg, changes)
            return
        # 其它事件类型暂忽略

    def _book_for(self, asset_id: Optional[str]) -> Optional[_BookState]:
        if not asset_id:
            return None
        asset_id = str(asset_id)
        # 仅缓存当前订阅的 token，避免服务端在重订阅竞态时推送旧数据被
        # 错误当作新行情。
        if asset_id not in self._active_tokens:
            return None
        b = self._books.get(asset_id)
        if b is None:
            b = _BookState(asset_id)
            self._books[asset_id] = b
        return b

    def _apply_book(self, msg: Dict[str, Any]) -> None:
        asset_id = msg.get("asset_id") or msg.get("market")
        b = self._book_for(asset_id)
        if b is None:
            return
        bids = _parse_levels(msg.get("bids"))
        asks = _parse_levels(msg.get("asks"))
        b.apply_snapshot(bids, asks)

    def _apply_price_change(self, msg: Dict[str, Any],
                            changes: Any) -> None:
        # 顶层可能直接带 asset_id；或每个 change 项自己带 asset_id。
        top_asset_id = msg.get("asset_id") or msg.get("market")
        if not isinstance(changes, list):
            return
        for ch in changes:
            if not isinstance(ch, dict):
                continue
            asset_id = ch.get("asset_id") or top_asset_id
            b = self._book_for(asset_id)
            if b is None:
                continue
            price = _coerce_float(ch.get("price"))
            size = _coerce_float(ch.get("size"))
            side = ch.get("side")
            b.apply_change(price, size, side)
