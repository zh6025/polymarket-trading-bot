import requests
import time
from lib.utils import APIClient, log_info, log_error, log_warn
from typing import Dict, List, Optional, Any

class PolymarketClient:
    """Polymarket API Client for market data and orderbook"""
    
    BASE_URL = "https://clob.polymarket.com"
    
    def __init__(self):
        self.client = APIClient(base_url="https://clob.polymarket.com")
    
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

    def place_order(self, token_id: str, side: str, price: float, size: float) -> dict:
        """
        Place a limit order on Polymarket CLOB.

        Args:
            token_id: The Polymarket token ID to trade
            side: 'BUY' or 'SELL'
            price: Limit price (0.0 - 1.0)
            size: Order size in USDC

        Returns:
            API response dict containing order ID and status
        """
        payload = {
            "tokenID": token_id,
            "side": side.upper(),
            "price": round(price, 4),
            "size": round(size, 2),
            "orderType": "GTC",
        }
        try:
            url = f"{self.BASE_URL}/order"
            log_info(f"Placing {side.upper()} order: token={token_id[:8]}... price={price:.4f} size={size:.2f}")
            response = self.client.post(url, payload)
            return response
        except Exception as e:
            log_error(f"Failed to place order: {e}")
            raise

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
