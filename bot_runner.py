#!/usr/bin/env python3
import sys
import asyncio
from lib.config import Config
from lib.utils import log_info, log_error, log_warn, sleep
from lib.polymarket_client import PolymarketClient
from lib.strategy import GridStrategy
from lib.risk import RiskManager

async def main():
    """Main program entry point"""
    
    print("╔═══════════════════════════════════════════════╗")
    print("║     Polymarket Trading Bot - Grid Strategy    ║")
    print("║          BTC Up/Down 5 Minute Markets         ║")
    print("╚═══════════════════════════════════════════════╝\n")
    
    try:
        # Load configuration
        config = Config()
        log_info(f"Configuration: {config.to_dict()}")
        
        # Find latest open event
        log_info("🔍 Finding latest open event for series: " + config.series_slug)
        event = await PolymarketClient.find_latest_open_event(config.series_slug)
        event_slug = event.get('slug')
        
        # Fetch event markets
        log_info("📊 Fetching event markets...")
        markets = PolymarketClient.fetch_event_markets(event_slug)
        
        # Filter tradable markets
        tradable_markets = PolymarketClient.filter_tradable_markets(markets)
        
        if not tradable_markets:
            log_warn("⚠️  No tradable markets found")
            return
        
        market = tradable_markets[0]
        log_info(f"📊 Selected market: {market.get('slug')} ({market.get('question')})")
        
        # Get tokens
        tokens = PolymarketClient.get_up_down_tokens(market)
        up_token = tokens['up_token']
        down_token = tokens['down_token']
        log_info(f"🎫 Up Token: {up_token}")
        log_info(f"🎫 Down Token: {down_token}")
        
        # Fetch orderbooks
        log_info("📊 Fetching orderbooks...")
        up_book = PolymarketClient.fetch_orderbook(up_token)
        down_book = PolymarketClient.fetch_orderbook(down_token)
        
        # Extract tick size and min order size
        tick_size = float(up_book.get('tick_size', 0.01))
        min_order_size = float(up_book.get('min_order_size', 5))
        log_info(f"✅ Tick size: {tick_size}, Min order size: {min_order_size}")
        
        # Calculate mid prices
        up_prices = PolymarketClient.calculate_mid_price(up_book)
        down_prices = PolymarketClient.calculate_mid_price(down_book)
        
        log_info(f"📈 Up Market - Bid: {up_prices['bid']:.2f}, Ask: {up_prices['ask']:.2f}, Mid: {up_prices['mid']:.2f}")
        log_info(f"📉 Down Market - Bid: {down_prices['bid']:.2f}, Ask: {down_prices['ask']:.2f}, Mid: {down_prices['mid']:.2f}")
        
        # Initialize strategy
        strategy = GridStrategy(config)
        strategy.validate_config(tick_size, min_order_size)
        
        # Generate grid levels
        levels = strategy.generate_grid_levels(up_prices['mid'], tick_size)
        
        # Generate order plan
        orders = strategy.generate_order_plan(
            up_prices['mid'],
            down_prices['mid'],
            up_token,
            down_token
        )
        
        # Display order plan
        print("\n" + "="*60)
        print("📋 ORDER PLAN (DRY-RUN)")
        print("="*60)
        
        sorted_orders = strategy.get_order_plan()
        for i, order in enumerate(sorted_orders, 1):
            print(f"{i:2d}. [{order['side']:4s}] {order['outcome']:4s} @ {order['price']:.2f} x {order['size']:5.0f}")
        
        print("="*60)
        print(f"Total Orders: {len(sorted_orders)}")
        
        if config.dry_run:
            log_info("✅ DRY-RUN completed (no orders placed)")
        else:
            log_warn("⚠️  Real trading not yet implemented")
        
    except Exception as e:
        log_error(f"❌ Fatal error: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

async def polling_loop():
    """Continuous polling loop"""
    log_info(f"🔄 Starting polling loop (interval: {Config().polling_interval}ms)")
    
    while True:
        try:
            await main()
            config = Config()
            sleep(config.polling_interval)
        except Exception as e:
            log_error(f"Polling cycle error: {str(e)}")
            sleep(Config().polling_interval)

if __name__ == '__main__':
    # Check command line arguments
    single_run = '--once' in sys.argv or len(sys.argv) > 1
    
    if single_run:
        # Single run
        asyncio.run(main())
    else:
        # Continuous polling
        try:
            asyncio.run(polling_loop())
        except KeyboardInterrupt:
            log_info("Shutting down...")
            sys.exit(0)