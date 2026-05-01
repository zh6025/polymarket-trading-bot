import requests
import time
from lib.utils import APIClient, log_info, log_error, log_warn
from typing import Dict, List, Optional, Any

# py_clob_client is required for real-money trading. Imports are deferred /
# guarded so that read-only usage (market data, dry-run) still works in
# environments where the SDK is not installed.
try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import ApiCreds, OrderArgs
    from py_clob_client.order_builder.constants import BUY, SELL
    _PY_CLOB_AVAILABLE = True
except Exception as _e:  # pragma: no cover - import guard
    ClobClient = None  # type: ignore
    ApiCreds = None  # type: ignore
    OrderArgs = None  # type: ignore
    BUY, SELL = "BUY", "SELL"
    _PY_CLOB_AVAILABLE = False
    _PY_CLOB_IMPORT_ERROR = _e


# py_clob_client signature_type constants:
#   0 = EOA            (你直接用 MetaMask 钱包，PRIVATE_KEY 就是该地址的私钥)
#   1 = POLY_PROXY     (邮箱/Magic 登录的 Polymarket 帐户，有一个由 EOA 控制的 Proxy 钱包，
#                       FUNDER 必须填这个 Proxy 地址，而不是 EOA 地址)
#   2 = POLY_GNOSIS_SAFE (用 MetaMask 登录后 Polymarket 给你创建的 Gnosis Safe，
#                         FUNDER 必须填 Safe 地址)
SIGNATURE_TYPE_EOA = 0
SIGNATURE_TYPE_POLY_PROXY = 1
SIGNATURE_TYPE_POLY_GNOSIS_SAFE = 2


class PolymarketClient:
    """Polymarket API Client for market data, orderbook, and CLOB trading.

    Read-only usage (market data only):
        client = PolymarketClient()

    Trading usage:
        client = PolymarketClient(
            host="https://clob.polymarket.com",
            chain_id=137,
            private_key="0x...",
            funder="0x...",            # Proxy / Safe address (NOT the EOA) when
                                        # signature_type != 0
            signature_type=1,           # 0=EOA, 1=POLY_PROXY, 2=POLY_GNOSIS_SAFE
            api_key=..., api_secret=..., api_passphrase=...,  # optional;
                                                              # auto-derived if omitted
        )
    """

    BASE_URL = "https://clob.polymarket.com"
    DEFAULT_CHAIN_ID = 137  # Polygon mainnet

    def __init__(
        self,
        host: Optional[str] = None,
        chain_id: Optional[int] = None,
        private_key: Optional[str] = None,
        funder: Optional[str] = None,
        signature_type: Optional[int] = None,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        api_passphrase: Optional[str] = None,
    ):
        self.client = APIClient(base_url=self.BASE_URL)
        self.host = host or self.BASE_URL
        self.chain_id = int(chain_id) if chain_id is not None else self.DEFAULT_CHAIN_ID
        self.private_key = private_key
        self.funder = funder
        self.signature_type = signature_type

        self._clob: Optional["ClobClient"] = None  # lazy
        self._api_creds_input = None
        if api_key and api_secret and api_passphrase:
            if not _PY_CLOB_AVAILABLE:
                log_warn("py_clob_client 未安装，提供的 API creds 将被忽略")
            else:
                self._api_creds_input = ApiCreds(
                    api_key=api_key,
                    api_secret=api_secret,
                    api_passphrase=api_passphrase,
                )

        # Eager initialization only if trading credentials supplied
        if self.private_key:
            try:
                self._init_clob_client()
            except Exception as e:
                # Don't crash the bot at construction time — trading methods
                # will surface a clear error when first invoked.
                log_error(f"初始化 CLOB 交易客户端失败（read-only 仍可用）: {e}")

    # ------------------------------------------------------------------ CLOB
    def _init_clob_client(self) -> "ClobClient":
        if self._clob is not None:
            return self._clob
        if not _PY_CLOB_AVAILABLE:
            raise RuntimeError(
                "py_clob_client 未安装，无法进行实盘交易。请先 `pip install py-clob-client`。"
            )
        if not self.private_key:
            raise RuntimeError("PRIVATE_KEY 未配置，无法进行实盘交易")
        if self.signature_type is None:
            raise RuntimeError(
                "SIGNATURE_TYPE 未配置 (0=EOA, 1=POLY_PROXY, 2=POLY_GNOSIS_SAFE)"
            )
        if self.signature_type != SIGNATURE_TYPE_EOA and not self.funder:
            raise RuntimeError(
                "SIGNATURE_TYPE != 0 时必须配置 FUNDER（Proxy/Safe 地址，"
                "不是 EOA 地址）"
            )

        log_info(
            f"初始化 CLOB 客户端: host={self.host} chain_id={self.chain_id} "
            f"signature_type={self.signature_type} funder={self.funder}"
        )
        clob = ClobClient(
            host=self.host,
            key=self.private_key,
            chain_id=self.chain_id,
            signature_type=self.signature_type,
            funder=self.funder,
        )

        # Set / derive L2 API creds (required to POST orders)
        creds = self._api_creds_input
        if creds is None:
            try:
                creds = clob.create_or_derive_api_creds()
                log_info("已自动派生 Polymarket API creds")
            except Exception as e:
                raise RuntimeError(
                    f"派生 API creds 失败（通常意味着私钥/funder/signature_type "
                    f"组合错误，或该账户从未在 Polymarket 网站激活过）: {e}"
                )
        clob.set_api_creds(creds)
        self._clob = clob
        return clob

    def get_wallet_status(self) -> Dict[str, Any]:
        """Return a small self-diagnostic dict useful at startup to confirm the
        signing/funder/api-creds combo is valid.

        Raises if the CLOB client cannot be initialized.
        """
        clob = self._init_clob_client()
        status: Dict[str, Any] = {
            "host": self.host,
            "chain_id": self.chain_id,
            "signature_type": self.signature_type,
            "funder": self.funder,
            "ok": True,
        }
        try:
            # get_address returns the EOA derived from PRIVATE_KEY
            status["address"] = clob.get_address()
        except Exception as e:
            status["address_error"] = str(e)
        try:
            # ping the auth-required endpoint to verify creds end-to-end
            status["ok_auth"] = bool(clob.get_api_keys())
        except Exception as e:
            status["ok"] = False
            status["auth_error"] = str(e)
        return status

    def place_order(
        self,
        token_id: str,
        side: str,
        price: float,
        size: float,
        order_type: str = "GTC",
    ) -> Dict[str, Any]:
        """Sign and submit an order to the Polymarket CLOB.

        Args:
            token_id: ERC1155 token id (string) of the outcome to buy/sell.
            side: 'buy' or 'sell' (case-insensitive).
            price: limit price in [0, 1].
            size: size in shares (the SDK takes share count, not USDC notional).
            order_type: 'GTC' (default) or 'FOK'.

        Returns the raw response dict from the CLOB.
        """
        clob = self._init_clob_client()
        side_norm = side.upper()
        if side_norm not in ("BUY", "SELL"):
            raise ValueError(f"side must be 'buy' or 'sell', got {side!r}")
        clob_side = BUY if side_norm == "BUY" else SELL

        order_args = OrderArgs(
            token_id=str(token_id),
            price=float(price),
            size=float(size),
            side=clob_side,
        )
        log_info(
            f"提交订单: token_id={token_id} side={side_norm} "
            f"price={price} size={size} type={order_type}"
        )
        signed = clob.create_order(order_args)
        resp = clob.post_order(signed, orderType=order_type)
        if isinstance(resp, dict) and not resp.get("success", True):
            log_error(f"ORDER FAILED: {resp}")
        else:
            log_info(f"ORDER OK: {resp}")
        return resp
    
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
