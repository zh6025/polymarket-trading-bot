#!/usr/bin/env python3
"""
bot_runner.py — Polymarket BTC 5-Minute Trading Bot

Strategy overview
-----------------
1. Find the active BTC-updown-5m market on Polymarket.
2. Fetch YES/NO orderbooks and compute mid-prices.
3. Apply price-window filters (configurable via env vars).
4. Use DirectionScorer (9 BTC market signals) to produce a direction signal.
   Falls back to simple mid-price ratio when SCORER_ENABLED=false.
5. Check mathematical feasibility of the hedge with hedge_formula.
6. Execute: place HEDGE order first, then MAIN order (safer fill order).
7. Log all signal scores and decision details.
"""
import sys
import time
import logging
from typing import Dict, Any, Optional

from lib.config import Config
from lib.utils import log_info, log_error, log_warn
from lib.polymarket_client import PolymarketClient
from lib.strategy import ProductionDecisionStrategy
from lib.direction_scorer import DirectionScorer
from lib.hedge_formula import (
    check_strategy_feasibility,
    compute_min_hedge_quantity,
    compute_profit_scenarios,
    optimal_hedge_with_kelly,
)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Simple fallback probability estimator (used when SCORER_ENABLED=false)
# ---------------------------------------------------------------------------
def estimate_win_prob(yes_mid: float, no_mid: float) -> float:
    """Simple mid-price probability ratio (fallback)."""
    total = yes_mid + no_mid
    if total <= 0:
        return 0.5
    return yes_mid / total


# ---------------------------------------------------------------------------
# Order placement (dry-run aware)
# ---------------------------------------------------------------------------
def maybe_place_order(
    client: PolymarketClient,
    token_id: str,
    side: str,
    price: float,
    size: float,
    dry_run: bool = True,
    label: str = "",
) -> Optional[Dict[str, Any]]:
    """
    Place an order or simulate placement in dry-run mode.

    Returns the order result dict, or None on failure.
    """
    order_info = {
        "token_id": token_id,
        "side": side,
        "price": price,
        "size": size,
        "label": label,
        "dry_run": dry_run,
    }
    if dry_run:
        log_info(
            f"[DRY-RUN] {label} order simulated: {side.upper()} "
            f"{size:.2f} USDC @ {price:.4f} (token={token_id[:12]}…)"
        )
        return {"status": "simulated", **order_info}

    try:
        # Real order placement via py-clob-client would go here.
        # For now we log and return a placeholder dict so the caller knows
        # the placement was attempted.
        log_info(
            f"[ORDER] {label}: {side.upper()} {size:.2f} USDC @ {price:.4f} "
            f"(token={token_id[:12]}…)"
        )
        # result = client.place_order(token_id, side, price, size)
        result = {"status": "placed", **order_info}
        return result
    except Exception as exc:
        log_error(f"[ORDER] {label} order failed: {exc}")
        return None


# ---------------------------------------------------------------------------
# Core trading cycle
# ---------------------------------------------------------------------------
def run_cycle(
    config: Config,
    client: PolymarketClient,
    decision_strategy: ProductionDecisionStrategy,
    scorer: Optional[DirectionScorer],
) -> None:
    """Execute a single trading cycle (find market → decide → trade)."""

    # 1. Find active BTC 5-min market
    log_info("🔍 Looking for active BTC 5-min market…")
    event = client.get_current_btc_5m_market()
    if not event:
        log_warn("⚠️  No active BTC 5-min market found — skipping cycle")
        return

    markets = event.get("markets", [])
    active = [m for m in markets if m.get("acceptingOrders", False) and not m.get("closed", True)]
    if not active:
        log_warn("⚠️  Market exists but has no accepting sub-markets — skipping")
        return

    # Identify YES and NO token IDs
    yes_market = next((m for m in active if m.get("outcomePrices") and "yes" in m.get("outcome", "").lower()), None)
    no_market  = next((m for m in active if m.get("outcomePrices") and "no"  in m.get("outcome", "").lower()), None)

    if not yes_market or not no_market:
        # Fallback: first two markets are YES/NO
        if len(active) >= 2:
            yes_market, no_market = active[0], active[1]
        else:
            log_warn("⚠️  Could not identify YES/NO markets — skipping")
            return

    yes_token_id = yes_market.get("clobTokenIds", [None])[0]
    no_token_id  = no_market.get("clobTokenIds", [None])[0]

    if not yes_token_id or not no_token_id:
        log_warn("⚠️  Missing token IDs — skipping")
        return

    # 2. Fetch orderbooks and compute mid prices
    try:
        yes_book = client.get_orderbook(yes_token_id)
        no_book  = client.get_orderbook(no_token_id)
    except Exception as exc:
        log_error(f"❌ Failed to fetch orderbooks: {exc}")
        return

    yes_prices = client.calculate_mid_price(yes_book)
    no_prices  = client.calculate_mid_price(no_book)

    yes_mid = yes_prices.get("mid")
    no_mid  = no_prices.get("mid")

    if yes_mid is None or no_mid is None:
        log_warn("⚠️  Could not calculate mid prices — skipping")
        return

    log_info(f"📊 YES mid={yes_mid:.4f}  NO mid={no_mid:.4f}")

    # 3. Inject token IDs into scorer (for orderbook depth signal)
    if scorer:
        scorer.yes_token_id = yes_token_id
        scorer.no_token_id  = no_token_id

    # 4. Compute direction signal
    if config.scorer_enabled and scorer:
        log_info("🤖 Running DirectionScorer…")
        scorer_result = scorer.compute_final_score()
    else:
        # Fallback: simple mid-price ratio
        prob = estimate_win_prob(yes_mid, no_mid)
        if prob > config.scorer_buy_threshold:
            direction = "BUY_YES"
        elif prob < config.scorer_sell_threshold:
            direction = "BUY_NO"
        else:
            direction = "SKIP"
        confidence = abs(prob - 0.5) * 2
        scorer_result = {
            "direction": direction,
            "probability": prob,
            "confidence": confidence,
            "raw_score": prob - 0.5,
            "signals": {},
        }
        log_info(f"[Fallback] direction={direction} prob={prob:.4f}")

    # 5. Apply ProductionDecisionStrategy (confidence + price window filters)
    decision = decision_strategy.decide(scorer_result, yes_mid, no_mid)

    if decision["action"] != "ENTER":
        log_info(f"⏭️  SKIP — {decision['reason']}")
        return

    direction   = decision["direction"]
    main_price  = decision["main_price"]
    hedge_price = decision["hedge_price"]

    # Determine which token is main and which is hedge
    if direction == "BUY_YES":
        main_token_id  = yes_token_id
        hedge_token_id = no_token_id
        main_label  = "MAIN(YES)"
        hedge_label = "HEDGE(NO)"
    else:  # BUY_NO
        main_token_id  = no_token_id
        hedge_token_id = yes_token_id
        main_label  = "MAIN(NO)"
        hedge_label = "HEDGE(YES)"

    Q_m = config.order_size  # main bet size in USDC
    fee = config.fee_rate

    # 6. Check mathematical feasibility
    feasibility = check_strategy_feasibility(main_price, hedge_price, fee)
    if not feasibility["feasible"]:
        log_warn(
            f"⚠️  Strategy not feasible — {feasibility['details']} — skipping"
        )
        return

    # 7. Compute hedge quantity
    win_prob = decision["probability"] if direction == "BUY_YES" else 1 - decision["probability"]
    kelly_result = optimal_hedge_with_kelly(main_price, Q_m, hedge_price, win_prob, fee)
    Q_h = kelly_result["hedge_quantity"]

    scenarios = compute_profit_scenarios(main_price, Q_m, hedge_price, Q_h, fee)
    log_info(
        f"💰 Profit scenarios: main_wins={scenarios['main_wins_profit']:.4f} "
        f"hedge_wins={scenarios['hedge_wins_profit']:.4f} "
        f"EV={scenarios['expected_value']:.4f}"
    )

    # 8. Execute — HEDGE FIRST, then MAIN (safer fill order)
    log_info(f"🚀 Placing {hedge_label} order first…")
    hedge_result = maybe_place_order(
        client,
        token_id=hedge_token_id,
        side="buy",
        price=hedge_price,
        size=Q_h,
        dry_run=config.dry_run,
        label=hedge_label,
    )

    if not hedge_result:
        log_error("❌ Hedge order failed — aborting main order (no naked exposure)")
        return

    log_info(f"✅ {hedge_label} placed — now placing {main_label}…")
    main_result = maybe_place_order(
        client,
        token_id=main_token_id,
        side="buy",
        price=main_price,
        size=Q_m,
        dry_run=config.dry_run,
        label=main_label,
    )

    if main_result:
        log_info(
            f"✅ Trade pair placed: {hedge_label}@{hedge_price:.4f} "
            f"+ {main_label}@{main_price:.4f}"
        )
    else:
        log_warn("⚠️  Main order failed after hedge was placed — manual review needed")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def main() -> None:
    print("""
╔═══════════════════════════════════════════════════════╗
║   Polymarket Trading Bot — 9-Signal Direction Scorer  ║
║         BTC Up/Down 5-Minute Markets                  ║
╚═══════════════════════════════════════════════════════╝
    """)

    try:
        config = Config()
        log_info(f"Configuration: {config.to_dict()}")

        client = PolymarketClient()

        decision_strategy = ProductionDecisionStrategy(
            min_confidence=config.min_confidence,
            main_price_min=config.main_price_min,
            main_price_max=config.main_price_max,
            hedge_price_min=config.hedge_price_min,
            hedge_price_max=config.hedge_price_max,
        )

        scorer: Optional[DirectionScorer] = None
        if config.scorer_enabled:
            scorer = DirectionScorer(
                steepness=config.scorer_steepness,
                buy_threshold=config.scorer_buy_threshold,
                sell_threshold=config.scorer_sell_threshold,
                polymarket_client=client,
            )
            log_info("✅ DirectionScorer enabled")
        else:
            log_warn("⚠️  DirectionScorer disabled — using simple mid-price ratio")

        polling_interval_s = config.polling_interval / 1000  # ms → s

        log_info(f"⏱  Polling every {polling_interval_s:.0f}s (DRY_RUN={config.dry_run})")
        log_info("Press Ctrl+C to stop.")

        while True:
            try:
                run_cycle(config, client, decision_strategy, scorer)
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                log_error(f"❌ Cycle error: {exc}")
                import traceback
                traceback.print_exc()

            log_info(f"⏳ Sleeping {polling_interval_s:.0f}s until next cycle…")
            time.sleep(polling_interval_s)

    except KeyboardInterrupt:
        log_info("🛑 Bot stopped by user")
    except Exception as exc:
        log_error(f"❌ Fatal error: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

