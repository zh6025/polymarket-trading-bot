#!/usr/bin/env python3
import sys
import logging
from lib.config import Config
from lib.utils import log_info, log_error, log_warn
from lib.polymarket_client import PolymarketClient

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def main():
    print("""
╔═══════════════════════════════════════════════╗
║     Polymarket Trading Bot - Grid Strategy    ║
║          BTC Up/Down 5 Minute Markets         ║
╚═══════════════════════════════════════════════╝
    """)
    
    try:
        # Load configuration
        config = Config()
        log_info(f"Configuration: {config.to_dict()}")
        
        # Initialize Polymarket client
        client = PolymarketClient()
        
        # Fetch markets
        log_info("🔍 Fetching Polymarket markets...")
        markets = client.get_markets()
        
        if not markets:
            log_warn("⚠️  No markets found")
            # Try with demo data
            print("\n" + "="*60)
            print("📊 Using Demo Market Data")
            print("="*60)
            demo_market = {
                'id': 'demo-btc-market',
                'question': 'Will Bitcoin go up in next 5 minutes?',
                'outcomes': ['Yes', 'No']
            }
            print(f"Market: {demo_market['question']}")
            print(f"Outcomes: {', '.join(demo_market['outcomes'])}")
            print("="*60)
            log_info("✅ Demo mode completed")
            return
        
        # Filter BTC markets
        btc_markets = client.filter_btc_markets(markets)
        
        if btc_markets:
            market = btc_markets[0]
            market_id = market.get('id')
            log_info(f"📈 Selected market: {market.get('question', market.get('id'))}")
            
            print("\n" + "="*60)
            print("✅ Bot successfully connected to Polymarket!")
            print(f"📈 Market ID: {market_id}")
            print(f"❓ Question: {market.get('question', 'N/A')}")
            print("="*60)
        else:
            print("\n" + "="*60)
            print("✅ Markets fetched from Polymarket!")
            print(f"📊 Total markets: {len(markets)}")
            if markets:
                print(f"📈 Sample market: {markets[0].get('question', markets[0].get('id'))}")
            print("="*60)
        
        log_info("✅ DRY-RUN completed successfully")
        
    except Exception as e:
        log_error(f"❌ Fatal error: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
