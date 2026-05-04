import requests
import time
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

    # 默认 tick / 最小订单
    DEFAULT_TICK_SIZE = 0.01
    MIN_ORDER_SIZE_USDC = 5.0  # Polymarket 最小订单金额

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

    def get_midpoint(self, token_id: str) -> Optional[float]:
        """获取 CLOB 实时中间价（best_bid+best_ask)/2。

        - 首选 CLOB `/midpoint?token_id=...`（毫秒级反映挂撤单变化）
        - 降级到 `/book` 用最优买卖价计算中点
        - 全部失败返回 None；调用方应回退到 Gamma `outcomePrices`
        """
        try:
            url = f"{self.BASE_URL}/midpoint?token_id={token_id}"
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                mid = data.get('mid') if isinstance(data, dict) else None
                if mid is not None:
                    val = float(mid)
                    if 0 < val < 1:
                        return val
        except Exception as e:
            log_warn(f"midpoint 接口失败，尝试 orderbook 计算: {e}")

        try:
            book = self.get_orderbook(token_id)
            if not isinstance(book, dict):
                return None
            bids = book.get('bids') or []
            asks = book.get('asks') or []

            def _best(levels, want_max):
                best = None
                for lvl in levels:
                    try:
                        p = float(lvl.get('price') if isinstance(lvl, dict) else lvl[0])
                    except (TypeError, ValueError, IndexError, AttributeError):
                        continue
                    if best is None or (p > best if want_max else p < best):
                        best = p
                return best

            best_bid = _best(bids, want_max=True)
            best_ask = _best(asks, want_max=False)
            if best_bid is not None and best_ask is not None:
                mid = (best_bid + best_ask) / 2.0
                if 0 < mid < 1:
                    return mid
            # 只有单边挂单时不返回伪中点，避免给出误导性价格；调用方会回退到 Gamma
        except Exception as e:
            log_warn(f"orderbook 计算 mid 失败: {e}")
        return None


    def get_btc_5m_market_by_slug(self, slug: str) -> Optional[Dict]:
        """通过 Gamma API 获取 BTC 5分钟市场"""
        try:
            url = f"https://gamma-api.polymarket.com/events/slug/{slug}"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data and isinstance(data, dict):
                    return data
            return None
        except Exception as e:
            log_error(f"Failed to fetch market by slug: {e}")
            return None

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
        # 只向未来找：offset=0是当前窗口，+300是下一个窗口，不往过去找（已结算）
        for offset in [0, 300, 600]:
            nearest_5min = (now + offset) - ((now + offset) % 300)
            slug = f"btc-updown-5m-{nearest_5min}"
            log_info(f"尝试市场 slug: {slug}")
            event = self.get_btc_5m_market_by_slug(slug)
            if event:
                markets = event.get('markets', [])
                # 必须 acceptingOrders=True 且未关闭
                active = [m for m in markets if m.get('acceptingOrders', False) and not m.get('closed', True)]
                if active:
                    log_info(f"找到活跃市场: {event.get('title', slug)}")
                    return event
                else:
                    log_warn(f"市场存在但已无活跃子市场，跳过: {slug}")
        log_error("未找到任何活跃的BTC 5分钟市场")
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
