import requests
import time
from urllib.parse import quote
from lib.utils import APIClient, log_info, log_error, log_warn
from lib.config import Config
from typing import Dict, List, Optional, Any


def _round_to_tick(price: float, tick: float) -> float:
    """把价格取整到指定 tick（如 0.01 / 0.001）。"""
    if tick <= 0:
        return price
    # 用整数避免浮点累积误差
    steps = round(price / tick)
    rounded = steps * tick
    # 根据 tick 精度限制小数位
    s = format(tick, 'f').rstrip('0')
    decimals = len(s.split('.')[-1]) if '.' in s else 0
    return round(rounded, decimals)


def _round_size(size: float, decimals: int = 2) -> float:
    """订单 size 取整到指定小数位（默认 0.01 USDC）。"""
    factor = 10 ** decimals
    # 用 floor 避免下单超过预算
    import math
    return math.floor(size * factor) / factor


class PolymarketClient:
    """Polymarket API Client：行情 + 实盘下单。

    实盘相关方法依赖 py_clob_client 与 POLY_PRIVATE_KEY/POLY_FUNDER 环境变量。
    DRY_RUN=true 或缺少私钥时，CLOB 客户端不会被初始化，行情接口仍可用。
    """

    BASE_URL = "https://clob.polymarket.com"
    GAMMA_BASE_URL = "https://gamma-api.polymarket.com"

    # 默认 tick / 最小订单名义金额
    DEFAULT_TICK_SIZE = 0.01
    MIN_ORDER_SIZE_USDC = 1.0  # Polymarket 最小订单名义金额（价格 × 数量）
    BTC_5M_WINDOW_SECONDS = 300
    # Search previous/current/next three 5-minute slugs to tolerate clock/API boundary drift.
    MARKET_SEARCH_OFFSETS_SECONDS = [-300, 0, 300, 600, 900]
    CLOCK_SKEW_TOLERANCE_SECONDS = 30
    MAX_FUTURE_MARKET_LOOKAHEAD_SECONDS = 900

    def __init__(self, config: Optional[Config] = None):
        self.client = APIClient(base_url=self.BASE_URL)
        self.config = config
        self._clob = None
        self._creds = None
        # 仅当配置齐备时初始化 CLOB 签名客户端
        if config is not None and config.poly_private_key and config.trading_enabled:
            try:
                self._init_clob_client()
            except Exception as e:
                log_error(f"初始化 CLOB 客户端失败: {e}")
                self._clob = None

    # ------------------------------------------------------------------
    # CLOB 实盘客户端
    # ------------------------------------------------------------------
    def _init_clob_client(self):
        """初始化 py_clob_client.ClobClient 并装配 L2 凭据。"""
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import ApiCreds

        cfg = self.config
        log_info(f"🔐 初始化 CLOB 客户端 (chain_id={cfg.poly_chain_id}, "
                 f"signature_type={cfg.poly_signature_type}, funder={cfg.poly_funder[:10]}...)")

        client = ClobClient(
            host=cfg.poly_clob_host,
            chain_id=cfg.poly_chain_id,
            key=cfg.poly_private_key,
            signature_type=cfg.poly_signature_type,
            funder=cfg.poly_funder or None,
        )

        # 优先使用预生成 L2 凭据；否则向 CLOB 派生
        if cfg.poly_api_key and cfg.poly_api_secret and cfg.poly_api_passphrase:
            creds = ApiCreds(
                api_key=cfg.poly_api_key,
                api_secret=cfg.poly_api_secret,
                api_passphrase=cfg.poly_api_passphrase,
            )
            log_info("🔑 使用环境变量中的 L2 API 凭据")
        else:
            creds = client.create_or_derive_api_creds()
            log_info("🔑 已派生 L2 API 凭据")
        client.set_api_creds(creds)

        self._clob = client
        self._creds = creds

    def _require_clob(self):
        if self._clob is None:
            raise RuntimeError(
                "CLOB 客户端未初始化：请确认 TRADING_ENABLED=true、"
                "POLY_PRIVATE_KEY/POLY_FUNDER 已配置，并安装了 py_clob_client。"
            )
        return self._clob

    def get_tick_size(self, token_id: str) -> float:
        """获取 token 的 tick size，失败时回退到 DEFAULT_TICK_SIZE。"""
        try:
            if self._clob is not None:
                ts = self._clob.get_tick_size(token_id)
                return float(ts)
        except Exception as e:
            log_warn(f"获取 tick_size 失败，使用默认 {self.DEFAULT_TICK_SIZE}: {e}")
        return self.DEFAULT_TICK_SIZE

    def get_balance_allowance(self, token_id: Optional[str] = None) -> Dict[str, Any]:
        """查询 USDC 余额或 conditional token 余额；返回 dict。"""
        from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
        client = self._require_clob()
        if token_id:
            params = BalanceAllowanceParams(asset_type=AssetType.CONDITIONAL, token_id=token_id)
        else:
            params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
        return client.get_balance_allowance(params)

    def place_order(
        self,
        token_id: str,
        side: str,
        price: float,
        size: float,
        order_type: str = 'GTC',
    ) -> Dict[str, Any]:
        """提交一笔订单到 Polymarket CLOB。

        参数:
            token_id: 目标 outcome 的 ERC1155 token id
            side:     'buy' / 'sell' / 'BUY' / 'SELL'
            price:    限价（0~1），会被 round 到 tick_size
            size:     订单大小（份额数量），会被 floor 到 0.01
            order_type: 'GTC' / 'FOK' / 'FAK' / 'GTD'

        返回 dict：{'order_id', 'status', 'price', 'size', 'side', 'raw'}
        失败会抛出异常。
        """
        from py_clob_client.clob_types import OrderArgs, OrderType
        from py_clob_client.order_builder.constants import BUY, SELL

        client = self._require_clob()
        side_norm = side.upper()
        if side_norm not in ('BUY', 'SELL'):
            raise ValueError(f"无效 side: {side}")
        side_const = BUY if side_norm == 'BUY' else SELL

        ot = order_type.upper()
        valid_types = ('GTC', 'FOK', 'FAK', 'GTD')
        if ot not in valid_types:
            raise ValueError(f"无效 order_type: {order_type}")
        order_type_enum = getattr(OrderType, ot)

        tick = self.get_tick_size(token_id)
        rounded_price = _round_to_tick(price, tick)
        rounded_size = _round_size(size, decimals=2)

        # 校验最小订单
        notional = rounded_price * rounded_size
        if notional < self.MIN_ORDER_SIZE_USDC:
            raise ValueError(
                f"订单金额 {notional:.4f} USDC 低于最小 {self.MIN_ORDER_SIZE_USDC}"
                f" (price={rounded_price}, size={rounded_size})"
            )
        if not (0 < rounded_price < 1):
            raise ValueError(f"价格越界: {rounded_price}")
        if rounded_size <= 0:
            raise ValueError(f"size <= 0: {rounded_size}")

        order_args = OrderArgs(
            token_id=token_id,
            price=rounded_price,
            size=rounded_size,
            side=side_const,
        )
        log_info(f"📤 下单: side={side_norm} price={rounded_price} size={rounded_size} "
                 f"tick={tick} type={ot} token={token_id[:12]}...")

        resp = client.create_and_post_order(order_args, order_type_enum)
        order_id = None
        status = None
        if isinstance(resp, dict):
            order_id = resp.get('orderID') or resp.get('order_id') or resp.get('id')
            status = resp.get('status')
        log_info(f"✅ 订单响应: order_id={order_id} status={status}")
        return {
            'order_id': order_id,
            'status': status,
            'price': rounded_price,
            'size': rounded_size,
            'side': side_norm,
            'raw': resp,
        }

    def get_order(self, order_id: str) -> Dict[str, Any]:
        """查询订单状态/成交。"""
        client = self._require_clob()
        return client.get_order(order_id)

    def cancel_order(self, order_id: str) -> Any:
        """撤单。"""
        client = self._require_clob()
        log_info(f"🛑 撤单: {order_id}")
        return client.cancel(order_id)

    # ------------------------------------------------------------------
    # 行情
    # ------------------------------------------------------------------
    def get_markets(self) -> List[Dict[str, Any]]:
        """Fetch markets list from CLOB"""
        try:
            url = f"{self.BASE_URL}/markets"
            log_info(f"Fetching markets from CLOB")
            response = self.client.get(url)
            markets = response if isinstance(response, list) else response.get('data', [])
            log_info(f"Found {len(markets)} markets")
            return markets
        except Exception as e:
            log_error(f"Failed to fetch markets: {e}")
            return []
    
    def filter_btc_markets(self, markets: List[Dict]) -> List[Dict]:
        """Filter BTC up/down markets"""
        btc_markets = [
            m for m in markets
            if m and ('BTC' in m.get('question', '').upper() or 'BITCOIN' in m.get('question', '').upper())
        ]
        log_info(f"Found {len(btc_markets)} BTC markets")
        return btc_markets
    
    def get_orderbook(self, token_id: str) -> Dict[str, Any]:
        """Fetch orderbook for a token"""
        try:
            url = f"{self.BASE_URL}/book?token_id={token_id}"
            log_info(f"Fetching orderbook for token")
            response = self.client.get(url)
            return response
        except Exception as e:
            log_error(f"Failed to fetch orderbook: {e}")
            raise
    
    def get_btc_5m_market_by_slug(self, slug: str) -> Optional[Dict]:
        """通过 Gamma API 获取 BTC 5分钟市场，兼容 path 和 query 两种 slug 路径。"""
        try:
            slug_q = quote(slug, safe='-')
            urls = [
                f"{self.GAMMA_BASE_URL}/events/slug/{slug_q}",
                f"{self.GAMMA_BASE_URL}/events?slug={slug_q}",
            ]
            for url in urls:
                response = requests.get(url, timeout=10)
                if response.status_code != 200:
                    log_warn(f"Gamma slug 查询失败 status={response.status_code} url={url}")
                    continue
                event = self._extract_gamma_event(response.json())
                if event:
                    return event
            return None
        except Exception as e:
            log_error(f"Failed to fetch market by slug: {e}")
            return None

    @staticmethod
    def _extract_gamma_event(data: Any) -> Optional[Dict]:
        """Gamma /events/slug 返回 dict，/events?slug= 返回 list 或 {'data': [...]}。"""
        if isinstance(data, dict):
            if data.get('slug') or data.get('markets'):
                return data
            events = data.get('data') or data.get('events')
            if isinstance(events, list) and events:
                return events[0] if isinstance(events[0], dict) else None
        if isinstance(data, list) and data:
            return data[0] if isinstance(data[0], dict) else None
        return None

    def _fetch_gamma_events(self, params: Dict[str, Any]) -> List[Dict]:
        """Fetch a Gamma events page and normalize common response shapes to a list."""
        try:
            response = requests.get(f"{self.GAMMA_BASE_URL}/events", params=params, timeout=10)
            if response.status_code != 200:
                log_warn(f"Gamma events 查询失败 status={response.status_code} params={params}")
                return []
            data = response.json()
            if isinstance(data, list):
                return [e for e in data if isinstance(e, dict)]
            if isinstance(data, dict):
                events = data.get('data') or data.get('events') or []
                if isinstance(events, list):
                    return [e for e in events if isinstance(e, dict)]
            return []
        except Exception as e:
            log_warn(f"Gamma events 查询异常: {e}")
            return []

    @staticmethod
    def _has_active_market(event: Dict) -> bool:
        markets = event.get('markets', []) or []
        return any(m.get('acceptingOrders', False) and not m.get('closed', True) for m in markets)

    @staticmethod
    def _btc_5m_slug_ts(event: Dict) -> Optional[int]:
        slug = str(event.get('slug', ''))
        if not slug.startswith('btc-updown-5m-'):
            return None
        try:
            return int(slug.rsplit('-', 1)[-1])
        except ValueError:
            return None

    def _is_btc_5m_market_time_valid(self, ts: int, now: int) -> bool:
        """Return True for current or near-future BTC 5m windows."""
        return (
            ts + self.BTC_5M_WINDOW_SECONDS > now - self.CLOCK_SKEW_TOLERANCE_SECONDS
            and ts <= now + self.MAX_FUTURE_MARKET_LOOKAHEAD_SECONDS
        )

    def _distance_from_now(self, event: Dict, now: int) -> float:
        ts = self._btc_5m_slug_ts(event)
        return abs(ts - now) if ts is not None else float('inf')

    def _find_active_btc_5m_market_from_gamma(self, now: int) -> Optional[Dict]:
        """Fallback：直接从 Gamma events 列表筛选当前活跃 BTC 5m 市场。"""
        param_sets = [
            {'closed': 'false', 'active': 'true', 'archived': 'false', 'limit': 100},
            {'closed': 'false', 'limit': 100},
        ]
        candidates: List[Dict] = []
        for params in param_sets:
            for event in self._fetch_gamma_events(params):
                ts = self._btc_5m_slug_ts(event)
                if ts is None:
                    continue
                if not self._has_active_market(event):
                    continue
                if not self._is_btc_5m_market_time_valid(ts, now):
                    continue
                candidates.append(event)
            if candidates:
                break
        if not candidates:
            return None
        candidates.sort(key=lambda event: self._distance_from_now(event, now))
        event = candidates[0]
        log_info(f"通过 Gamma events 列表找到活跃市场: {event.get('slug')}")
        return event

    def get_server_time(self) -> int:
        """从Polymarket API响应头获取服务器时间，失败则用本地时间"""
        try:
            resp = requests.head("https://clob.polymarket.com/", timeout=5)
            date_str = resp.headers.get("Date", "")
            if date_str:
                from email.utils import parsedate_to_datetime
                server_dt = parsedate_to_datetime(date_str)
                server_ts = int(server_dt.timestamp())
                local_ts = int(time.time())
                diff = server_ts - local_ts
                if abs(diff) > 2:
                    log_warn(f"本地时间与服务器相差 {diff}s，使用服务器时间")
                return server_ts
        except Exception as e:
            log_warn(f"获取服务器时间失败，使用本地时间: {e}")
        return int(time.time())

    def get_current_btc_5m_market(self) -> Optional[Dict]:
        """获取当前活跃的 BTC 5分钟市场（以Polymarket时间为准，不依赖本地时间���算）"""
        now = self.get_server_time()
        # 先按 slug 精确找；包含 -300 秒以兼容 Polymarket 窗口起点/服务器时间轻微偏差。
        for offset in self.MARKET_SEARCH_OFFSETS_SECONDS:
            nearest_5min = (now + offset) - ((now + offset) % self.BTC_5M_WINDOW_SECONDS)
            slug = f"btc-updown-5m-{nearest_5min}"
            log_info(f"尝试市场 slug: {slug}")
            event = self.get_btc_5m_market_by_slug(slug)
            if event:
                event_ts = self._btc_5m_slug_ts(event)
                event_remaining = event_ts + self.BTC_5M_WINDOW_SECONDS - now if event_ts else None
                if event_ts is None or not self._is_btc_5m_market_time_valid(event_ts, now):
                    if event_remaining is not None:
                        time_msg = f"remaining={event_remaining}s" if event_remaining > 0 else f"expired_by={abs(event_remaining)}s"
                    else:
                        time_msg = "remaining=unknown"
                    log_warn(f"市场已过期或时间无效，跳过: {event.get('slug', slug)} {time_msg}")
                    continue
                if self._has_active_market(event):
                    log_info(f"找到活跃市场: {event.get('title', slug)} slug={event.get('slug', slug)} remaining={event_remaining}s")
                    return event
                else:
                    log_warn(f"市场存在但已无活跃子市场，跳过: {slug}")
        fallback = self._find_active_btc_5m_market_from_gamma(now)
        if fallback:
            return fallback
        log_error("未找到任何活跃的BTC 5分钟市场")
        return None

    def get_midpoint(self, token_id: str) -> Optional[float]:
        """获取 CLOB 实时 midpoint；失败时回退到 /book 计算 bid/ask mid。"""
        if not token_id:
            return None
        try:
            response = self.client.get(f"{self.BASE_URL}/midpoint?token_id={token_id}")
            if isinstance(response, dict):
                raw_mid = response.get('mid') or response.get('midpoint')
                if raw_mid is not None:
                    mid = float(raw_mid)
                    if 0 < mid < 1:
                        return mid
        except Exception as e:
            log_warn(f"获取 CLOB midpoint 失败，回退 orderbook: {e}")

        try:
            book = self.get_orderbook(token_id)
            mid_data = self.calculate_mid_price(book)
            mid = mid_data.get('mid')
            return float(mid) if mid is not None else None
        except Exception as e:
            log_warn(f"通过 orderbook 计算 midpoint 失败: {e}")
            return None

    def calculate_mid_price(self, book: Dict[str, Any]) -> Dict[str, float]:
        """Calculate bid/ask/mid from orderbook"""
        try:
            bids = book.get('bids', [])
            asks = book.get('asks', [])

            # bids升序(最高买单在末尾), asks降序(最低卖单在末尾)
            best_bid = float(bids[-1].get('price', 0)) if bids else None
            best_ask = float(asks[-1].get('price', 1)) if asks else None

            # 双边都有流动性：正常计算
            if best_bid is not None and best_ask is not None:
                mid_price = (best_bid + best_ask) / 2
                return {'bid': best_bid, 'ask': best_ask, 'mid': mid_price}

            # 只有卖单（市场倾向于0）
            if best_ask is not None:
                log_warn(f"orderbook只有卖单, ask={best_ask}")
                return {'bid': 0.0, 'ask': best_ask, 'mid': best_ask}

            # 只有买单（市场倾向于1）
            if best_bid is not None:
                log_warn(f"orderbook只有买单, bid={best_bid}")
                return {'bid': best_bid, 'ask': 1.0, 'mid': best_bid}

            # 完全没有订单
            log_warn("orderbook为空，无法计算价格")
            return {'bid': None, 'ask': None, 'mid': None}

        except Exception as e:
            log_error(f"Failed to calculate mid price: {e}")
            return {'bid': None, 'ask': None, 'mid': None}
