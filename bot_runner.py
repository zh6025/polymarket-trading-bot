#!/usr/bin/env python3
"""
Polymarket Trading Bot — Production Runner

Uses the momentum hedge strategy with Kelly-optimal bet sizing.
Defaults to dry-run mode (no real orders). Set TRADING_ENABLED=true
and DRY_RUN=false in .env only after validating with bot_simulate.py.
"""

import asyncio
import logging
import sys
from datetime import datetime

from lib.config import Config
from lib.polymarket_client import PolymarketClient
from lib.trading_engine import TradingEngine
from lib.data_persistence import DataPersistence
from lib.bot_state import (
    load_state, save_state, reset_daily_if_needed,
    record_trade_open, halt_bot, MarketPosition,
)
from lib.decision import ProductionDecisionStrategy
from lib.utils import log_info, log_error, log_warn

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


async def trading_loop(config: Config):
    """Main trading loop."""
    log_info("Initialising components…")
    client = PolymarketClient(
        host=config.host,
        chain_id=config.chain_id,
        private_key=config.private_key,
        proxy_address=config.proxy_address,
    )
    engine = TradingEngine(dry_run=config.dry_run)
    db = DataPersistence()
    strategy = ProductionDecisionStrategy(config=config)

    # Load persisted state (crash recovery)
    state = load_state(config.state_file_path)
    state = reset_daily_if_needed(state)
    save_state(state, config.state_file_path)

    cycle = 0
    log_info(
        f"Bot started — dry_run={config.dry_run}, "
        f"trading_enabled={config.trading_enabled}, "
        f"threshold={config.momentum_threshold:.0%}"
    )

    while True:
        try:
            cycle += 1
            log_info(f"── Cycle #{cycle} ──────────────────────────────────────")

            # Reset daily counters if day rolled over
            state = reset_daily_if_needed(state)

            # Halt guard
            if state.is_halted:
                log_warn(f"Bot halted: {state.halt_reason}. Waiting…")
                await asyncio.sleep(config.polling_interval)
                continue

            # Fetch the current BTC 5-minute market
            event = client.get_current_btc_5m_market()
            if not event:
                log_warn("No active BTC 5-minute market found. Waiting…")
                await asyncio.sleep(config.polling_interval)
                continue

            markets = event.get("markets", [])
            active_markets = [
                m for m in markets
                if m.get("acceptingOrders", False) and not m.get("closed", True)
            ]
            if not active_markets:
                log_warn("Market exists but no active sub-markets. Waiting…")
                await asyncio.sleep(config.polling_interval)
                continue

            market = active_markets[0]
            tokens = market.get("tokens", []) or market.get("clobTokenIds", [])

            if len(tokens) < 2:
                log_warn("Cannot extract YES/NO tokens. Skipping.")
                await asyncio.sleep(config.polling_interval)
                continue

            yes_token_id = tokens[0].get("token_id") if isinstance(tokens[0], dict) else tokens[0]
            no_token_id = tokens[1].get("token_id") if isinstance(tokens[1], dict) else tokens[1]

            # Fetch orderbook prices
            yes_prices = client.calculate_mid_price(client.get_orderbook(yes_token_id))
            no_prices = client.calculate_mid_price(client.get_orderbook(no_token_id))

            yes_mid = yes_prices.get("mid")
            no_mid = no_prices.get("mid")

            if yes_mid is None or no_mid is None:
                log_warn(f"Incomplete prices (yes={yes_mid}, no={no_mid}). Skipping.")
                await asyncio.sleep(config.polling_interval)
                continue

            log_info(
                f"Market: {event.get('title', 'N/A')[:60]} | "
                f"YES={yes_mid:.4f}  NO={no_mid:.4f}"
            )

            market_data = {
                "yes_price": yes_mid,
                "no_price": no_mid,
                "yes_token_id": yes_token_id,
                "no_token_id": no_token_id,
            }

            # Decision
            result = strategy.decide(market_data, state, config)
            log_info(f"Decision: {result.decision} — {result.decision_reason}")

            if result.decision == "SKIP":
                log_info(f"Skipping: {result.skip_reasons}")
                await asyncio.sleep(config.polling_interval)
                continue

            # Guard: TRADING_ENABLED must be true for real orders
            if not config.trading_enabled and not config.dry_run:
                log_warn("TRADING_ENABLED=false — skipping order placement.")
                await asyncio.sleep(config.polling_interval)
                continue

            # Place main bet
            main_order_id = engine.place_order(
                token_id=result.main_token_id,
                side=result.main_side,
                price=result.main_price,
                size=result.main_size,
            )
            state = record_trade_open(
                state,
                MarketPosition(
                    token_id=result.main_token_id,
                    outcome=result.main_outcome,
                    side=result.main_side,
                    price=result.main_price,
                    size=result.main_size,
                    timestamp=datetime.now().isoformat(),
                    market_question=event.get("title", ""),
                ),
            )
            db.save_trade({
                "order_id": main_order_id,
                "token_id": result.main_token_id,
                "side": result.main_side,
                "price": result.main_price,
                "size": result.main_size,
                "timestamp": datetime.now().isoformat(),
            })

            # Place hedge bet (optional)
            if result.should_trade_hedge:
                hedge_order_id = engine.place_order(
                    token_id=result.hedge_token_id,
                    side=result.hedge_side,
                    price=result.hedge_price,
                    size=result.hedge_size,
                )
                state = record_trade_open(
                    state,
                    MarketPosition(
                        token_id=result.hedge_token_id,
                        outcome=result.hedge_outcome,
                        side=result.hedge_side,
                        price=result.hedge_price,
                        size=result.hedge_size,
                        timestamp=datetime.now().isoformat(),
                        market_question=event.get("title", ""),
                    ),
                )
                db.save_trade({
                    "order_id": hedge_order_id,
                    "token_id": result.hedge_token_id,
                    "side": result.hedge_side,
                    "price": result.hedge_price,
                    "size": result.hedge_size,
                    "timestamp": datetime.now().isoformat(),
                })

            # Halt check: consecutive losses
            if state.consecutive_losses >= config.consecutive_loss_limit:
                state = halt_bot(state, f"consecutive_losses={state.consecutive_losses}")

            save_state(state, config.state_file_path)

            stats = engine.get_statistics()
            log_info(
                f"Stats — total_orders={stats['total_orders']}, "
                f"daily_trades={state.daily_trade_count}, "
                f"daily_pnl={state.daily_pnl:+.2f} USDC"
            )

            await asyncio.sleep(config.polling_interval)

        except KeyboardInterrupt:
            log_info("Keyboard interrupt — shutting down.")
            break
        except Exception as e:
            log_error(f"Unexpected error in cycle #{cycle}: {e}")
            import traceback
            traceback.print_exc()
            await asyncio.sleep(config.polling_interval)

    save_state(state, config.state_file_path)
    log_info("Bot stopped.")


def main():
    print("""
╔═══════════════════════════════════════════════════╗
║   Polymarket Trading Bot — Momentum Hedge Mode    ║
║   BTC Up/Down 5-Minute Binary Markets             ║
╚═══════════════════════════════════════════════════╝
    """)

    config = Config()
    log_info(f"Config: {config.to_dict()}")

    if not config.dry_run and not config.trading_enabled:
        log_error(
            "DRY_RUN=false but TRADING_ENABLED=false. "
            "Set TRADING_ENABLED=true to enable live trading."
        )
        sys.exit(1)

    if config.dry_run:
        log_info("Running in DRY-RUN mode — no real orders will be placed.")
    else:
        log_warn("LIVE TRADING MODE — real orders will be placed!")

    asyncio.run(trading_loop(config))


if __name__ == "__main__":
    main()
