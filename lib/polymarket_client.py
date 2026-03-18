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

    def get_current_btc_5m_market(self) -> Optional[Dict]:
        """获取当前时间窗口的 BTC 5分钟市场，失败则尝试下一个或上一个窗口"""
        now = int(time.time())
        for offset in [0, 300, -300]:
            nearest_5min = (now + offset) - ((now + offset) % 300)
            slug = f"btc-updown-5m-{nearest_5min}"
            log_info(f"尝试市场 slug: {slug}")
            event = self.get_btc_5m_market_by_slug(slug)
            if event:
                markets = event.get('markets', [])
                active = [m for m in markets if m.get('acceptingOrders', False) and not m.get('closed', True)]
                if active:
                    log_info(f"找到活跃市场: {event.get('title', slug)}")
                    return event
        return None

    def calculate_mid_price(self, book: Dict[str, Any]) -> Dict[str, float]:
        """Calculate bid/ask/mid from orderbook"""
        try:
            bids = book.get('bids', [])
            asks = book.get('asks', [])
            
            if not bids or not asks:
                return {'bid': 0.5, 'ask': 0.5, 'mid': 0.5}
            
            bid_price = float(bids[0].get('price', 0.5))
            ask_price = float(asks[0].get('price', 0.5))
            mid_price = (bid_price + ask_price) / 2
            
            return {
                'bid': bid_price,
                'ask': ask_price,
                'mid': mid_price
            }
        except Exception as e:
            log_error(f"Failed to calculate mid price: {e}")
            return {'bid': 0.5, 'ask': 0.5, 'mid': 0.5}
