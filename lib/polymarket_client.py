from lib.utils import APIClient, log_info, log_error, log_warn
from typing import Dict, List, Optional, Any

class PolymarketClient:
    """Polymarket API Client for market data and orderbook"""
    
    BASE_URL = "https://polymarket.com"
    API_URL = "https://clob.polymarket.com"
    
    def __init__(self):
        self.client = APIClient()
    
    def get_event_by_slug(self, event_slug: str) -> Dict[str, Any]:
        """Fetch event details by slug"""
        try:
            url = f"{self.BASE_URL}/api/event/slug?slug={event_slug}"  
            log_info(f"Fetching event: {event_slug}")
            return self.client.get(url)
        except Exception as e:
            log_error(f"Failed to fetch event {event_slug}: {e}")
            raise
    
    def get_series_by_slug(self, series_slug: str) -> Dict[str, Any]:
        """Fetch series with all events"""
        try:
            url = f"{self.BASE_URL}/api/series?slug={series_slug}"
            log_info(f"Fetching series: {series_slug}")
            return self.client.get(url)
        except Exception as e:
            log_error(f"Failed to fetch series {series_slug}: {e}")
            raise
    
    def find_latest_open_event(self, series_slug: str) -> Dict[str, Any]:
        """Find the latest open event in a series"""
        try:
            series = self.get_series_by_slug(series_slug)
            events = series.get('events', [])
            
            # Filter open events (closed=false)
            open_events = [e for e in events if e and not e.get('closed', True)]
            
            if not open_events:
                raise Exception(f"No open events found in series: {series_slug}")
            
            # Sort by endDate (desc), then startDate (desc)
            open_events.sort(
                key=lambda e: (
                    -int(e.get('endDate', 0)),
                    -int(e.get('startDate', 0))
                )
            )
            
            chosen = open_events[0]
            log_info(f"Found open event: {chosen.get('slug')}")
            return chosen
        except Exception as e:
            log_error(f"Failed to find latest open event: {e}")
            raise
    
    def get_event_markets(self, event_slug: str) -> List[Dict[str, Any]]:
        """Get all markets for an event"""
        try:
            event = self.get_event_by_slug(event_slug)
            markets = event.get('markets', [])
            log_info(f"Found {len(markets)} markets in event {event_slug}")
            return markets
        except Exception as e:
            log_error(f"Failed to fetch event markets: {e}")
            raise
    
    def filter_tradable_markets(self, markets: List[Dict]) -> List[Dict]:
        """Filter markets that are tradable"""
        tradable = [
            m for m in markets
            if m and m.get('acceptingOrders') and not m.get('closed') and m.get('active')
        ]
        log_info(f"Found {len(tradable)} tradable markets")
        return tradable
    
    def get_orderbook(self, token_id: str) -> Dict[str, Any]:
        """Fetch orderbook for a token"""
        try:
            url = f"{self.API_URL}/book?token_id={token_id}"
            response = self.client.get(url, headers={'Accept': 'application/json'})
            log_info(f"Fetched orderbook for token: {token_id}")
            return response
        except Exception as e:
            log_error(f"Failed to fetch orderbook for {token_id}: {e}")
            raise
    
    def calculate_mid_price(self, book: Dict[str, Any]) -> Dict[str, float]:
        """Calculate bid/ask/mid from orderbook"""
        try:
            bids = book.get('bids', [])
            asks = book.get('asks', [])
            
            if not bids or not asks:
                raise Exception("Invalid orderbook: missing bids or asks")
            
            bid_price = float(bids[0].get('price', 0))
            ask_price = float(asks[0].get('price', 0))
            mid_price = (bid_price + ask_price) / 2
            
            return {
                'bid': bid_price,
                'ask': ask_price,
                'mid': mid_price
            }
        except Exception as e:
            log_error(f"Failed to calculate mid price: {e}")
            raise
    
    def get_up_down_tokens(self, market: Dict[str, Any]) -> Dict[str, str]:
        """Get Up and Down token IDs from market"""
        try:
            token_ids = market.get('clobTokenIds', [])
            if len(token_ids) < 2:
                raise Exception("Invalid market: missing clobTokenIds")
            
            return {
                'up_token': token_ids[0],
                'down_token': token_ids[1]
            }
        except Exception as e:
            log_error(f"Failed to get tokens: {e}")
            raise
