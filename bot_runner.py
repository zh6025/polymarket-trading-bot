#!/usr/bin/env python3
"""
bot_runner.py — Single-shot dry-run / smoke-test entry point.

Fetches the current BTC 5-min market, runs the DirectionScorer on live
Binance 1-min klines, and prints the recommended action.  No real orders
are placed unless DRY_RUN=false AND TRADING_ENABLED=true.

Execution order (when trading):
  1. Place HEDGE order (if enabled and decision == ENTER_MAIN_AND_HEDGE)
  2. Wait for hedge fill confirmation
  3. Place MAIN order
"""
import sys
import logging
from datetime import datetime

from lib.config import Config
from lib.utils import log_info, log_error, log_warn
from lib.polymarket_client import PolymarketClient
from lib.direction_scorer import DirectionScorer
from lib.hedge_formula import scenario_summary, is_strategy_viable
from lib.btc_price_feed import get_btc_klines, get_btc_price, extract_closes, extract_volumes
from lib.decision import (
    make_trade_decision, format_decision_log,
    SKIP, ENTER_MAIN_ONLY, ENTER_MAIN_AND_HEDGE,
)

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def _compute_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, period + 1):
        diff = closes[-period - 1 + i] - closes[-period - 2 + i]
        (gains if diff > 0 else losses).append(abs(diff))
    avg_gain = sum(gains) / period if gains else 0
    avg_loss = sum(losses) / period if losses else 1e-9
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def _compute_ema(closes, period):
    if len(closes) < period:
        return closes[-1] if closes else 0
    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for p in closes[period:]:
        ema = p * k + ema * (1 - k)
    return ema


def build_scorer_signals(klines):
    """Build DirectionScorer signal dict from Binance klines."""
    closes = extract_closes(klines)
    vols = extract_volumes(klines)

    if len(closes) < 10:
        return {}

    ema_fast = _compute_ema(closes, 3)
    ema_slow = _compute_ema(closes, 8)
    prev_closes = closes[:-1]
    prev_ema_fast = _compute_ema(prev_closes, 3) if len(prev_closes) >= 3 else ema_fast
    prev_ema_slow = _compute_ema(prev_closes, 8) if len(prev_closes) >= 8 else ema_slow

    rsi = _compute_rsi(closes)
    prev_rsi = _compute_rsi(closes[:-1]) if len(closes) > 15 else rsi

    avg_vol = sum(vols[:-1]) / max(len(vols) - 1, 1)
    current_vol = vols[-1]
    price_change = (closes[-1] - closes[-2]) if len(closes) >= 2 else 0

    scorer = DirectionScorer()
    return {
        "ema_cross": scorer.score_ema_cross(ema_fast, ema_slow, prev_ema_fast, prev_ema_slow),
        "rsi_trend": scorer.score_rsi(rsi, prev_rsi),
        "volume_surge": scorer.score_volume_surge(current_vol, avg_vol, price_change),
    }


def main():
    print("""
╔═══════════════════════════════════════════════╗
║    Polymarket Trading Bot — DirectionScorer   ║
║         BTC Up/Down 5 Minute Markets          ║
╚═══════════════════════════════════════════════╝
    """)

    try:
        config = Config()
        log_info(f"Configuration: {config.to_dict()}")

        client = PolymarketClient()
        scorer = DirectionScorer()

        # --- BTC kline signal ---
        log_info("📡 Fetching BTC 1-min klines from Binance...")
        klines = get_btc_klines(interval="1m", limit=30)
        btc_price = get_btc_price()
        log_info(f"BTC spot price: {btc_price}")

        signals = build_scorer_signals(klines)
        score_result = scorer.compute_final_score(signals)

        print("\n" + "=" * 60)
        print("📊 DirectionScorer Result")
        print("=" * 60)
        print(f"  Total score : {score_result['total_score']}")
        print(f"  Prob UP     : {score_result['prob_up'] * 100:.1f}%")
        print(f"  Prob DOWN   : {score_result['prob_down'] * 100:.1f}%")
        print(f"  Action      : {score_result['action']}  (confidence: {score_result['confidence']})")
        print("=" * 60)

        # --- Fetch active market ---
        log_info("🔍 Fetching current BTC 5-min Polymarket market...")
        event = client.get_current_btc_5m_market()

        if not event:
            log_warn("⚠️  No active 5-min BTC market found — exiting.")
            return

        markets = event.get("markets", [])
        active = [m for m in markets if m.get("acceptingOrders", False) and not m.get("closed", True)]
        if not active:
            log_warn("No accepting sub-markets found.")
            return

        market = active[0]
        tokens = market.get("tokens") or market.get("clobTokenIds", [])
        if len(tokens) < 2:
            log_warn("Could not extract two tokens from market.")
            return

        up_token = tokens[0]
        down_token = tokens[1]
        up_token_id = up_token.get("token_id", up_token) if isinstance(up_token, dict) else up_token
        down_token_id = down_token.get("token_id", down_token) if isinstance(down_token, dict) else down_token

        # Fetch orderbooks
        try:
            up_book = client.get_orderbook(up_token_id)
            down_book = client.get_orderbook(down_token_id)
            up_prices = client.calculate_mid_price(up_book)
            down_prices = client.calculate_mid_price(down_book)
        except Exception as exc:
            log_error(f"Failed to fetch orderbooks: {exc}")
            return

        up_ask = up_prices.get("ask", 0.5)
        down_ask = down_prices.get("ask", 0.5)
        spread_pct = abs(up_ask - down_ask)

        # Approximate seconds remaining (300s window)
        seconds_remaining = 300

        # Decision gates
        decision, reason = make_trade_decision(
            seconds_remaining=seconds_remaining,
            min_remaining_seconds=config.min_secs_main_entry,
            main_ask=up_ask if score_result["action"] == "BUY_YES" else down_ask,
            main_max_price=config.main_max_price,
            hedge_ask=down_ask if score_result["action"] == "BUY_YES" else up_ask,
            hedge_max_price=config.hedge_max_price_decision,
            spread_pct=spread_pct,
            max_spread_pct=config.max_spread_pct,
            depth_ok=True,
            hard_stop_secs=config.hard_stop_new_entry_sec,
            enable_hedge=config.enable_hedge,
        )

        log_info(format_decision_log(
            cycle=1,
            market_slug=market.get("market_slug", "unknown"),
            decision=decision,
            reason=reason,
            main_ask=up_ask,
            seconds_remaining=seconds_remaining,
        ))

        print(f"\n  Market action : {score_result['action']}")
        print(f"  Gate decision : {decision}  ({reason})")
        print(f"  UP ask={up_ask:.4f}  DOWN ask={down_ask:.4f}")

        if decision == SKIP or score_result["action"] == "SKIP" or score_result["confidence"] == "LOW":
            print("\n⏭️  No trade — signal weak or gates blocked.")
            return

        # --- Hedge formula summary ---
        main_price = up_ask if score_result["action"] == "BUY_YES" else down_ask
        hedge_price = down_ask if score_result["action"] == "BUY_YES" else up_ask
        main_qty = config.main_bet_size_usdc

        if is_strategy_viable(main_price, hedge_price):
            from lib.hedge_formula import min_hedge_quantity
            hedge_qty = min_hedge_quantity(main_price, main_qty, hedge_price)
            summary = scenario_summary(main_price, main_qty, hedge_price, hedge_qty)
            print("\n📋 Hedge Scenario Summary:")
            for k, v in summary.items():
                print(f"   {k}: {v}")

        # --- Order placement (DRY_RUN by default) ---
        if config.dry_run:
            print(f"\n[DRY-RUN] Would place orders — no real trades executed.")
        else:
            if not config.trading_enabled:
                print("\n⚠️  TRADING_ENABLED=false — set to true to place real orders.")
                return
            log_warn("Live trading enabled — implement real order placement via py-clob-client.")

        log_info("✅ bot_runner completed.")

    except Exception as exc:
        log_error(f"❌ Fatal error: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
