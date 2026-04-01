"""
bot_runner.py: Main entry point for the BTC 5-minute Polymarket multi-window trading bot.

Strategy overview:
  - Monitors BTC 5-minute Polymarket markets
  - Builds market bias from BTC real-time data (Binance)
  - Enters single-direction positions at key time windows before market close
  - Window 0 (~260-275s remaining): optional early momentum entry (disabled by default)
  - Mid-review (~115-125s remaining): stop-out window 0 if direction flipped
  - Window 1 (~90-95s remaining): primary entry
  - Window 2 (~30-35s remaining): stop-loss or late strong entry
  - Never buys above hard cap price (default 0.85)
  - Dry-run mode enabled by default for safety
"""
import logging
import time
import sys

from lib.config import Config
from lib.bot_state import BotState
from lib.session_state import SessionState
from lib.market_data import MarketDataFetcher
from lib.market_bias import compute_bias
from lib.window_strategy import run_window_strategy
from lib.execution import execute_decision
from lib.polymarket_client import PolymarketClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


def get_market_tokens(event: dict) -> dict:
    """Extract UP and DOWN token IDs from a market event"""
    tokens = {'UP': None, 'DOWN': None}
    markets = event.get('markets', [])
    for m in markets:
        outcomes = m.get('outcomes', [])
        token_ids = m.get('clobTokenIds', [])
        for i, outcome in enumerate(outcomes):
            outcome_upper = outcome.upper()
            if outcome_upper in ('UP', 'YES') and i < len(token_ids):
                tokens['UP'] = token_ids[i]
            elif outcome_upper in ('DOWN', 'NO') and i < len(token_ids):
                tokens['DOWN'] = token_ids[i]
    return tokens


def get_market_end_time(event: dict) -> float:
    """Extract market end time as unix timestamp"""
    for m in event.get('markets', []):
        end_date = m.get('endDate') or m.get('endDateIso') or m.get('endTime')
        if end_date:
            try:
                from datetime import datetime, timezone
                if isinstance(end_date, (int, float)):
                    return float(end_date)
                dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                return dt.timestamp()
            except Exception:
                pass
    return 0.0


def run_trading_cycle(
    config: Config,
    bot_state: BotState,
    session: SessionState,
    client: PolymarketClient,
    data_fetcher: MarketDataFetcher,
) -> bool:
    """
    Run one polling cycle of the trading bot.
    Returns True if we should continue, False if trading is blocked.
    """
    # 1. Check global risk limits
    can_trade, reason = bot_state.can_trade(
        daily_loss_limit=config.DAILY_LOSS_LIMIT_USDC,
        daily_trade_limit=config.DAILY_TRADE_LIMIT,
        consec_loss_limit=config.CONSECUTIVE_LOSS_LIMIT,
    )
    if not can_trade:
        log.warning(f"Trading blocked: {reason}")
        return False

    # 2. Fetch current BTC 5m market
    try:
        event = client.get_current_btc_5m_market()
    except Exception as e:
        log.error(f"Failed to fetch market: {e}")
        return True

    if not event:
        log.info("No active BTC 5m market found, waiting...")
        return True

    market_slug = event.get('slug', '')
    market_end_time = get_market_end_time(event)
    now = time.time()
    secs_remaining = max(0.0, market_end_time - now) if market_end_time > 0 else 0.0

    # 3. Reset session if this is a new market
    if session.is_new_market(market_slug):
        log.info(f"New market detected: {market_slug} | {secs_remaining:.0f}s remaining")
        session.reset_for_new_market(market_slug, market_end_time)

    # 4. If market is ending with an open position, record outcome
    if secs_remaining < 5 and session.has_position:
        log.info(f"Market ending with open position in {session.position_direction}")
        session.close_position(pnl=0.0)  # PnL determined by Polymarket settlement
        bot_state.record_trade(0.0)
        bot_state.save()
        return True

    # 5. Skip if outside all trading windows
    if secs_remaining < 25 or secs_remaining > 300:
        log.debug(f"Outside trading windows ({secs_remaining:.0f}s remaining), skipping")
        return True

    # 6. Fetch BTC snapshot for bias computation
    btc_snap = data_fetcher.get_btc_snapshot()

    # Data delay safety check
    if btc_snap and (now - btc_snap.timestamp) > config.BTC_DATA_MAX_AGE_SEC:
        log.warning(f"BTC data is stale ({now - btc_snap.timestamp:.0f}s old), skipping")
        return True

    # 7. Compute market bias
    bias = compute_bias(
        btc=btc_snap,
        momentum_5m_threshold=config.MOMENTUM_5M_THRESHOLD,
        momentum_15m_threshold=config.MOMENTUM_15M_THRESHOLD,
    )
    log.info(f"Market: {market_slug} | {secs_remaining:.0f}s remaining | Bias: {bias.value}")

    # 8. Fetch orderbook snapshots for UP and DOWN tokens
    tokens = get_market_tokens(event)
    ob_up = data_fetcher.get_orderbook_snapshot(client, tokens['UP']) if tokens['UP'] else None
    ob_down = data_fetcher.get_orderbook_snapshot(client, tokens['DOWN']) if tokens['DOWN'] else None

    # 9. Get recent volatility for safety check
    recent_volatility = data_fetcher.get_recent_price_change(seconds=10)

    # 10. Run window strategy
    decision = run_window_strategy(
        session=session,
        secs_remaining=secs_remaining,
        bias=bias,
        ob_up=ob_up,
        ob_down=ob_down,
        bet_size=config.BET_SIZE_USDC,
        hard_cap_price=config.HARD_CAP_PRICE,
        window0_enabled=config.WINDOW0_ENABLED,
        min_confidence_w0=config.MIN_CONFIDENCE_W0,
        min_confidence_w1=config.MIN_CONFIDENCE_W1,
        late_entry_min_price=config.LATE_ENTRY_MIN_PRICE,
        max_spread=config.MAX_SPREAD,
        min_depth=config.MIN_DEPTH,
        recent_volatility=recent_volatility,
        max_recent_volatility=config.MAX_RECENT_VOLATILITY,
    )

    log.info(f"Decision: {decision.action} | window={decision.window} | {decision.reason}")

    # 11. Execute decision
    if decision.action in ('ENTER', 'STOP_LOSS'):
        result = execute_decision(
            decision=decision,
            polymarket_client=client,
            dry_run=config.DRY_RUN,
        )

        if result and result.success:
            if decision.action == 'ENTER':
                session.open_position(
                    direction=decision.direction,
                    token_id=decision.token_id,
                    entry_price=decision.price,
                    size=decision.size,
                )
                log.info(
                    f"✅ Position opened: {decision.direction} @ {decision.price:.4f} "
                    f"size={decision.size:.2f} {'[DRY RUN]' if config.DRY_RUN else ''}"
                )
            elif decision.action == 'STOP_LOSS':
                pnl_estimate = (decision.price - session.position_entry_price) * session.position_size
                if session.position_direction == 'DOWN':
                    pnl_estimate = -pnl_estimate
                session.close_position(pnl=pnl_estimate)
                bot_state.record_trade(pnl_estimate)
                bot_state.save()
                log.info(
                    f"🛑 Stop-loss executed: {decision.direction} @ {decision.price:.4f} "
                    f"estimated_pnl={pnl_estimate:.3f} {'[DRY RUN]' if config.DRY_RUN else ''}"
                )
        elif result and not result.success:
            log.error(f"Order failed: {result.error}")

    return True


def main():
    log.info("🤖 BTC 5m Polymarket Multi-Window Trading Bot starting...")

    config = Config()
    log.info(
        f"Config: DRY_RUN={config.DRY_RUN} TRADING_ENABLED={config.TRADING_ENABLED} "
        f"BET_SIZE={config.BET_SIZE_USDC} WINDOW0={config.WINDOW0_ENABLED}"
    )

    if not config.TRADING_ENABLED:
        log.warning("⚠️  TRADING_ENABLED=false — running in observation mode (no orders placed)")
    if config.DRY_RUN:
        log.info("🔬 DRY_RUN=true — all orders simulated")

    bot_state = BotState.load()
    bot_state.trading_enabled = config.TRADING_ENABLED
    session = SessionState()
    client = PolymarketClient()
    data_fetcher = MarketDataFetcher()

    interval_sec = config.POLLING_INTERVAL / 1000.0
    log.info(f"Starting main loop (polling every {interval_sec:.1f}s)")

    while True:
        try:
            run_trading_cycle(
                config=config,
                bot_state=bot_state,
                session=session,
                client=client,
                data_fetcher=data_fetcher,
            )
        except KeyboardInterrupt:
            log.info("⛔ Interrupted by user")
            bot_state.save()
            break
        except Exception as e:
            log.error(f"Unexpected error in trading cycle: {e}", exc_info=True)

        time.sleep(interval_sec)


if __name__ == '__main__':
    main()
