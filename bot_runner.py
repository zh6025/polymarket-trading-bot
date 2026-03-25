#!/usr/bin/env python3
"""
Single-shot production decision runner for the Polymarket BTC 5m trading bot.

Designed to be called once per cron/scheduler tick. It:
  1. Loads configuration and persistent state.
  2. Finds the current active BTC 5m market.
  3. Fetches order books for both outcomes (main leg + hedge).
  4. Runs risk checks (daily loss limit, cooldown, trade cap).
  5. Uses ProductionDecisionStrategy to decide whether to trade.
  6. Places orders (skipped in dry-run mode).
  7. Saves updated state.
"""

import sys
import time
import json
import logging

from lib.config import load_config
from lib.utils import log_info, log_error, log_warn
from lib.polymarket_client import PolymarketClient
from lib.bot_state import load_state, save_state, reset_daily_if_needed, record_trade_open
from lib.strategy import ProductionDecisionStrategy
from lib.risk import RiskManager

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

BANNER = """
╔══════════════════════════════════════════════════════╗
║    Polymarket BTC 5m Bot — Single-Shot Runner        ║
╚══════════════════════════════════════════════════════╝
"""


def _extract_token_pair(event: dict) -> tuple:
    """
    Return (main_token_id, hedge_token_id, main_outcome, hedge_outcome)
    from a Gamma API event dict, or four empty strings on failure.
    """
    for market in event.get("markets", []):
        if not market.get("acceptingOrders", False) or market.get("closed", False):
            continue
        raw = market.get("clobTokenIds", "[]")
        token_ids = json.loads(raw) if isinstance(raw, str) else raw
        if len(token_ids) >= 2:
            return token_ids[0], token_ids[1], "YES", "NO"
    return "", "", "", ""


def _book_depth_usdc(book: dict, side: str = "bids") -> float:
    """Sum the USDC value of all levels on one side of the book."""
    total = 0.0
    for level in book.get(side, []):
        try:
            total += float(level["price"]) * float(level["size"])
        except (KeyError, ValueError):
            pass
    return total


def main() -> None:
    print(BANNER)
    config = load_config()

    mode_label = "🟡 DRY-RUN (no real orders)" if config.dry_run else "🔴 LIVE TRADING"
    log_info(f"Mode: {mode_label}")

    now_ts = int(time.time())

    # ── State ─────────────────────────────────────────────────────────────────
    state = load_state(config.state_file_path, config.trading_enabled)
    reset_daily_if_needed(state, now_ts)

    if not state.trading_enabled:
        log_warn("Trading is disabled in state — exiting")
        save_state(state, config.state_file_path)
        sys.exit(0)

    # ── Risk gatekeeper ───────────────────────────────────────────────────────
    risk = RiskManager(config)

    # ── Clients ───────────────────────────────────────────────────────────────
    client = PolymarketClient(
        host=config.host,
        chain_id=config.chain_id,
        private_key=config.private_key,
        proxy_address=config.proxy_address,
    )
    strategy = ProductionDecisionStrategy(config)

    # ── Market discovery ──────────────────────────────────────────────────────
    log_info("Looking for active BTC 5m market…")
    try:
        event = client.get_current_btc_5m_market()
    except Exception as exc:
        log_error(f"Market discovery failed: {exc}")
        save_state(state, config.state_file_path)
        sys.exit(0)

    if not event:
        log_warn("No active BTC 5m market — nothing to do")
        save_state(state, config.state_file_path)
        sys.exit(0)

    market_id = event.get("id", event.get("slug", "unknown"))
    log_info(f"Market: {event.get('title', market_id)}")

    # ── One-position-per-market guard ─────────────────────────────────────────
    if config.one_position_per_market and state.market_has_position(market_id):
        log_info(f"Already have a position in {market_id} — skipping")
        save_state(state, config.state_file_path)
        sys.exit(0)

    # ── Global risk check ─────────────────────────────────────────────────────
    allowed, reason = risk.check_global_risk(
        market_id=market_id,
        current_pnl=state.daily_realized_pnl_usdc,
        now_ts=now_ts,
    )
    if not allowed:
        log_warn(f"Risk check blocked entry: {reason}")
        save_state(state, config.state_file_path)
        sys.exit(0)

    # ── Token IDs ─────────────────────────────────────────────────────────────
    main_token_id, hedge_token_id, main_outcome, hedge_outcome = _extract_token_pair(event)
    if not main_token_id:
        log_warn("Could not extract token IDs from event — skipping")
        save_state(state, config.state_file_path)
        sys.exit(0)

    # ── Order books ───────────────────────────────────────────────────────────
    try:
        main_book = client.get_orderbook(main_token_id)
        hedge_book = client.get_orderbook(hedge_token_id)
    except Exception as exc:
        log_error(f"Failed to fetch order books: {exc}")
        save_state(state, config.state_file_path)
        sys.exit(0)

    main_prices = client.calculate_mid_price(main_book)
    hedge_prices = client.calculate_mid_price(hedge_book)

    if main_prices["mid"] is None or hedge_prices["mid"] is None:
        log_warn("Order book is empty or one-sided — skipping")
        save_state(state, config.state_file_path)
        sys.exit(0)

    # Estimate elapsed seconds from the market start (from slug timestamp)
    elapsed_sec = 0.0
    try:
        import re
        slug = event.get("slug", "")
        m = re.search(r"btc-updown-5m-(\d+)", slug)
        if m:
            market_start_ts = int(m.group(1))
            elapsed_sec = max(0.0, now_ts - market_start_ts)
    except Exception:
        pass

    # ── Strategy decision ─────────────────────────────────────────────────────
    decision = strategy.decide(
        main_outcome=main_outcome,
        main_token_id=main_token_id,
        main_price=main_prices["mid"],
        main_bid=main_prices["bid"] or 0.0,
        main_ask=main_prices["ask"] or 1.0,
        main_depth_usdc=_book_depth_usdc(main_book, "bids"),
        hedge_outcome=hedge_outcome,
        hedge_token_id=hedge_token_id,
        hedge_price=hedge_prices["mid"],
        hedge_bid=hedge_prices["bid"] or 0.0,
        hedge_ask=hedge_prices["ask"] or 1.0,
        hedge_depth_usdc=_book_depth_usdc(hedge_book, "bids"),
        elapsed_sec=elapsed_sec,
    )

    log_info(f"Decision: {decision.decision} — {decision.decision_reason}")

    if decision.decision != "TRADE":
        log_info("Skipping this cycle")
        save_state(state, config.state_file_path)
        sys.exit(0)

    # ── Execute ───────────────────────────────────────────────────────────────
    if config.dry_run:
        log_info(
            f"[DRY-RUN] Would place MAIN {main_outcome} @ {main_prices['ask']:.4f} "
            f"x {decision.main_size:.2f} USDC"
        )
        if decision.should_trade_hedge:
            log_info(
                f"[DRY-RUN] Would place HEDGE {hedge_outcome} @ {hedge_prices['ask']:.4f} "
                f"x {decision.hedge_size:.2f} USDC"
            )
    else:
        log_info(f"Placing MAIN order: {main_outcome} @ {main_prices['ask']:.4f} x {decision.main_size}")
        client.place_order(main_token_id, "buy", main_prices["ask"], decision.main_size)

        if decision.should_trade_hedge:
            log_info(f"Placing HEDGE order: {hedge_outcome} @ {hedge_prices['ask']:.4f} x {decision.hedge_size}")
            client.place_order(hedge_token_id, "buy", hedge_prices["ask"], decision.hedge_size)

    # ── Update state ──────────────────────────────────────────────────────────
    record_trade_open(
        state=state,
        market_id=market_id,
        now_ts=now_ts,
        main_outcome=main_outcome,
        main_token_id=main_token_id,
        main_price=main_prices["ask"] or main_prices["mid"],
        main_size=decision.main_size,
        hedge_outcome=hedge_outcome,
        hedge_token_id=hedge_token_id,
        hedge_price=hedge_prices["ask"] or hedge_prices["mid"],
        hedge_size=decision.hedge_size,
    )
    risk.record_trade(market_id, now_ts)
    save_state(state, config.state_file_path)

    log_info("✅ Run complete")


if __name__ == "__main__":
    main()
