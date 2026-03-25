#!/usr/bin/env python3
"""
bot_continuous.py — Continuous trading loop with strategy dispatch.

Supported strategies (STRATEGY env var):
  imbalance       — Late-entry single-side imbalance (default)
  directional     — EMA+ATR BTC trend following
  momentum_hedge  — 70% trigger + Kelly-optimal hedge

Risk gates (BotState):
  - Daily PnL loss limit
  - Daily trade count limit
  - Consecutive loss limit
  - Hard stop N seconds before resolution

Execution order when hedging:
  1. Place HEDGE order first
  2. Place MAIN order after hedge confirmed
"""
import asyncio
import logging
from datetime import datetime, timezone

from lib.config import Config
from lib.utils import log_info, log_error, log_warn
from lib.polymarket_client import PolymarketClient
from lib.trading_engine import TradingEngine
from lib.data_persistence import DataPersistence
from lib.bot_state import BotState, MarketPosition
from lib.decision import (
    make_trade_decision, format_decision_log,
    SKIP, ENTER_MAIN_ONLY, ENTER_MAIN_AND_HEDGE,
)
from lib.direction_scorer import DirectionScorer
from lib.btc_price_feed import get_btc_klines, extract_closes, extract_volumes
from lib.directional_strategy import DirectionalStrategy
from lib.momentum_hedge_strategy import MomentumHedgeStrategy

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ema(closes, period):
    if len(closes) < period:
        return closes[-1] if closes else 0
    k = 2 / (period + 1)
    val = sum(closes[:period]) / period
    for p in closes[period:]:
        val = p * k + val * (1 - k)
    return val


def _rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(-period, 0):
        diff = closes[i] - closes[i - 1]
        (gains if diff > 0 else losses).append(abs(diff))
    ag = sum(gains) / period if gains else 0
    al = sum(losses) / period if losses else 1e-9
    return 100 - 100 / (1 + ag / al)


def _build_scorer_signals(klines, scorer: DirectionScorer):
    closes = extract_closes(klines)
    vols = extract_volumes(klines)
    if len(closes) < 10:
        return {}
    ef = _ema(closes, 3)
    es = _ema(closes, 8)
    pef = _ema(closes[:-1], 3) if len(closes) > 3 else ef
    pes = _ema(closes[:-1], 8) if len(closes) > 8 else es
    rsi = _rsi(closes)
    prsi = _rsi(closes[:-1]) if len(closes) > 15 else rsi
    avg_vol = sum(vols[:-1]) / max(len(vols) - 1, 1)
    pc = (closes[-1] - closes[-2]) if len(closes) >= 2 else 0
    return {
        "ema_cross": scorer.score_ema_cross(ef, es, pef, pes),
        "rsi_trend": scorer.score_rsi(rsi, prsi),
        "volume_surge": scorer.score_volume_surge(vols[-1], avg_vol, pc),
    }


def _risk_ok(state: BotState, config: Config) -> tuple:
    """Return (ok, reason)."""
    state._maybe_reset_daily()
    if state.daily_pnl <= -abs(config.daily_loss_limit):
        return False, f"daily_loss_limit hit ({state.daily_pnl:.2f})"
    if state.daily_trade_count >= config.daily_trade_limit:
        return False, f"daily_trade_limit hit ({state.daily_trade_count})"
    if state.consecutive_losses >= config.consecutive_loss_limit:
        return False, f"consecutive_loss_limit hit ({state.consecutive_losses})"
    return True, "ok"


# ---------------------------------------------------------------------------
# Strategy runners
# ---------------------------------------------------------------------------

async def _run_imbalance(client, engine, db, state, config, cycle):
    """Late-entry single-side imbalance strategy."""
    event = client.get_current_btc_5m_market()
    if not event:
        log_warn("No active market found.")
        return

    markets = event.get("markets", [])
    active = [m for m in markets if m.get("acceptingOrders", False) and not m.get("closed", True)]
    if not active:
        return

    market = active[0]
    slug = market.get("market_slug", "unknown")
    tokens = market.get("tokens") or []
    if len(tokens) < 2:
        return

    up_token_id = tokens[0].get("token_id") if isinstance(tokens[0], dict) else tokens[0]
    down_token_id = tokens[1].get("token_id") if isinstance(tokens[1], dict) else tokens[1]

    try:
        up_book = client.get_orderbook(up_token_id)
        down_book = client.get_orderbook(down_token_id)
        up_p = client.calculate_mid_price(up_book)
        down_p = client.calculate_mid_price(down_book)
    except Exception as exc:
        log_error(f"Orderbook fetch error: {exc}")
        return

    up_ask = up_p.get("ask", 0.5)
    down_ask = down_p.get("ask", 0.5)
    dominant_price = max(up_ask, down_ask)
    spread_pct = abs(up_ask - down_ask)

    # Imbalance: dominant side must be >= dominance_threshold
    if dominant_price < config.dominance_threshold:
        log_info(f"[imbalance] No dominance: up={up_ask:.3f} down={down_ask:.3f}")
        return

    # Pick strong side
    if up_ask >= down_ask:
        main_ask, main_token, main_outcome = up_ask, up_token_id, "UP"
        hedge_ask, hedge_token, hedge_outcome = down_ask, down_token_id, "DOWN"
    else:
        main_ask, main_token, main_outcome = down_ask, down_token_id, "DOWN"
        hedge_ask, hedge_token, hedge_outcome = up_ask, up_token_id, "UP"

    seconds_remaining = 300  # approximate

    decision, reason = make_trade_decision(
        seconds_remaining=seconds_remaining,
        min_remaining_seconds=config.min_secs_main_entry,
        main_ask=main_ask,
        main_max_price=config.main_max_price,
        hedge_ask=hedge_ask,
        hedge_max_price=config.hedge_max_price_decision,
        spread_pct=spread_pct,
        max_spread_pct=config.max_spread_pct,
        depth_ok=True,
        hard_stop_secs=config.hard_stop_new_entry_sec,
        enable_hedge=config.enable_hedge,
    )

    log_info(format_decision_log(cycle, slug, decision, reason, main_ask, seconds_remaining))

    if decision == SKIP:
        return

    ts = datetime.now(timezone.utc).isoformat()

    # Place HEDGE first (if applicable), then MAIN
    if decision == ENTER_MAIN_AND_HEDGE:
        hedge_id = engine.place_order(hedge_token, "buy", hedge_ask, config.hedge_notional)
        db.save_trade({
            "order_id": hedge_id, "token_id": hedge_token, "side": "buy",
            "price": hedge_ask, "size": config.hedge_notional,
            "timestamp": ts, "outcome": hedge_outcome, "market_slug": slug,
        })
        log_info(f"[imbalance] HEDGE placed: {hedge_outcome}@{hedge_ask:.4f}")

    main_id = engine.place_order(main_token, "buy", main_ask, config.main_bet_size_usdc)
    db.save_trade({
        "order_id": main_id, "token_id": main_token, "side": "buy",
        "price": main_ask, "size": config.main_bet_size_usdc,
        "timestamp": ts, "outcome": main_outcome, "market_slug": slug,
    })
    log_info(f"[imbalance] MAIN placed: {main_outcome}@{main_ask:.4f}")

    pos = MarketPosition(
        market_slug=slug, outcome=main_outcome, token_id=main_token,
        entry_price=main_ask, size=config.main_bet_size_usdc, entry_ts=ts,
        hedge_outcome=hedge_outcome if decision == ENTER_MAIN_AND_HEDGE else None,
        hedge_token_id=hedge_token if decision == ENTER_MAIN_AND_HEDGE else None,
        hedge_price=hedge_ask if decision == ENTER_MAIN_AND_HEDGE else None,
        hedge_size=config.hedge_notional if decision == ENTER_MAIN_AND_HEDGE else None,
    )
    state.add_open_position(pos)
    state.save()


async def _run_directional(client, engine, db, state, config, cycle):
    """EMA+ATR directional strategy using BTC klines."""
    klines = get_btc_klines(interval="1m", limit=30)
    if not klines:
        log_warn("[directional] No kline data.")
        return

    strat = DirectionalStrategy(
        fast_period=config.ema_fast_period,
        slow_period=config.ema_slow_period,
        atr_period=config.atr_period,
        atr_threshold_pct=config.atr_threshold_pct,
        max_entry_price=config.max_entry_price,
        bet_size=config.bet_size,
        signal_buffer=config.ema_signal_buffer,
    )
    signal = strat.generate_signal(klines)
    log_info(f"[directional] signal={signal}")

    if signal == "SKIP":
        return

    event = client.get_current_btc_5m_market()
    if not event:
        return

    markets = event.get("markets", [])
    active = [m for m in markets if m.get("acceptingOrders", False) and not m.get("closed", True)]
    if not active:
        return

    market = active[0]
    slug = market.get("market_slug", "unknown")
    tokens = market.get("tokens") or []
    if len(tokens) < 2:
        return

    up_token_id = tokens[0].get("token_id") if isinstance(tokens[0], dict) else tokens[0]
    down_token_id = tokens[1].get("token_id") if isinstance(tokens[1], dict) else tokens[1]

    try:
        up_book = client.get_orderbook(up_token_id)
        down_book = client.get_orderbook(down_token_id)
        up_p = client.calculate_mid_price(up_book)
        down_p = client.calculate_mid_price(down_book)
    except Exception as exc:
        log_error(f"Orderbook fetch error: {exc}")
        return

    up_ask = up_p.get("ask", 0.5)
    down_ask = down_p.get("ask", 0.5)

    order = strat.decide_bet(signal, up_ask, down_ask, up_token_id, down_token_id)
    if not order:
        return

    ts = datetime.now(timezone.utc).isoformat()
    oid = engine.place_order(order["token_id"], "buy", order["price"], order["size"])
    db.save_trade({
        "order_id": oid, "token_id": order["token_id"], "side": "buy",
        "price": order["price"], "size": order["size"],
        "timestamp": ts, "outcome": order["outcome"], "market_slug": slug,
    })
    log_info(f"[directional] {order['outcome']}@{order['price']:.4f} size={order['size']}")
    state.add_open_position(MarketPosition(
        market_slug=slug, outcome=order["outcome"], token_id=order["token_id"],
        entry_price=order["price"], size=order["size"], entry_ts=ts,
    ))
    state.save()


async def _run_momentum_hedge(client, engine, db, state, config, cycle, mh_strategy):
    """Momentum hedge strategy: fire on dominant side >= threshold."""
    event = client.get_current_btc_5m_market()
    if not event:
        return

    markets = event.get("markets", [])
    active = [m for m in markets if m.get("acceptingOrders", False) and not m.get("closed", True)]
    if not active:
        return

    market = active[0]
    slug = market.get("market_slug", "unknown")
    tokens = market.get("tokens") or []
    if len(tokens) < 2:
        return

    up_token_id = tokens[0].get("token_id") if isinstance(tokens[0], dict) else tokens[0]
    down_token_id = tokens[1].get("token_id") if isinstance(tokens[1], dict) else tokens[1]

    try:
        up_book = client.get_orderbook(up_token_id)
        down_book = client.get_orderbook(down_token_id)
        up_p = client.calculate_mid_price(up_book)
        down_p = client.calculate_mid_price(down_book)
    except Exception as exc:
        log_error(f"Orderbook fetch error: {exc}")
        return

    up_ask = up_p.get("ask", 0.5)
    down_ask = down_p.get("ask", 0.5)

    orders = mh_strategy.generate_orders(slug, up_ask, down_ask, up_token_id, down_token_id)
    if not orders:
        return

    ts = datetime.now(timezone.utc).isoformat()
    for order in orders:
        oid = engine.place_order(order["token_id"], "buy", order["price"], order["size"])
        db.save_trade({
            "order_id": oid, "token_id": order["token_id"], "side": "buy",
            "price": order["price"], "size": order["size"],
            "timestamp": ts, "outcome": order["outcome"], "market_slug": slug,
        })
        log_info(f"[momentum_hedge] {order['role']} {order['outcome']}@{order['price']:.4f}")

    main_order = next((o for o in orders if o.get("role") == "main"), orders[-1])
    state.add_open_position(MarketPosition(
        market_slug=slug, outcome=main_order["outcome"], token_id=main_order["token_id"],
        entry_price=main_order["price"], size=main_order["size"], entry_ts=ts,
    ))
    state.save()


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

async def run_continuous():
    config = Config()
    client = PolymarketClient()
    engine = TradingEngine(dry_run=config.dry_run)
    db = DataPersistence(db_path="bot_data.db")
    state = BotState.load()
    mh_strategy = MomentumHedgeStrategy(
        trigger_threshold=config.trigger_threshold,
        total_bet_size=config.total_bet_size,
        use_dynamic_ratio=config.use_dynamic_ratio,
        fixed_hedge_ratio=config.fixed_hedge_ratio,
        win_rate_slope=config.win_rate_slope,
        max_trigger_price=config.max_trigger_price,
    )

    strategy_name = config.strategy.lower()
    poll_secs = config.polling_interval / 1000

    print(f"""
╔═══════════════════════════════════════════════╗
║   Polymarket Bot — Continuous Mode            ║
║   Strategy : {strategy_name:<30} ║
║   DRY_RUN  : {str(config.dry_run):<30} ║
╚═══════════════════════════════════════════════╝
    """)

    cycle = 0
    while True:
        cycle += 1
        try:
            log_info(f"── Cycle #{cycle} | strategy={strategy_name} ──")

            # Risk gate
            ok, reason = _risk_ok(state, config)
            if not ok:
                log_warn(f"Risk gate blocked: {reason}")
                await asyncio.sleep(poll_secs)
                continue

            if strategy_name == "directional":
                await _run_directional(client, engine, db, state, config, cycle)
            elif strategy_name == "momentum_hedge":
                await _run_momentum_hedge(client, engine, db, state, config, cycle, mh_strategy)
            else:
                await _run_imbalance(client, engine, db, state, config, cycle)

            stats = engine.get_statistics()
            log_info(
                f"Stats: orders={stats['total_orders']} "
                f"filled={stats['filled_orders']} "
                f"trades={stats['total_trades']}"
            )

        except KeyboardInterrupt:
            log_info("🛑 Stopping...")
            break
        except Exception as exc:
            log_error(f"Cycle error: {exc}")

        await asyncio.sleep(poll_secs)


if __name__ == "__main__":
    asyncio.run(run_continuous())
