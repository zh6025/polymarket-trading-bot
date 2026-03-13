"""Main bot runner.

Entry point for the Polymarket BTC Up/Down 5-minute trading bot.

Usage:
    python runner.py

Environment variables are loaded from .env (see .env.example).

Safety gate:
    Live trading requires TRADING_MODE=live.  All other values activate
    DRY_RUN mode where orders are logged but not placed.
"""
from __future__ import annotations

import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Load .env before any module-level config reads
load_dotenv()

import structlog  # noqa: E402  (imported after dotenv)

from feeds.binance import BinanceFeed
from feeds.chainlink import ChainlinkFeed
from polymarket.client import PolymarketClient
from polymarket.market_discovery import discover_active_market
from polymarket.models import Order, OrderBook, Outcome, Side, OrderStatus
from risk.limits import RiskLimits, RiskManager
from risk.pnl import PnLTracker
from storage.db import Database
from strategy.divergence import get_ask_prices, is_diverged
from strategy.signals import Trend, get_trend, is_trend_reversal
from strategy.state_machine import MarketSession, MarketState

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_log_level,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
)
logging.basicConfig(
    stream=sys.stdout,
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(message)s",
)
logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DRY_RUN: bool = os.environ.get("TRADING_MODE", "dry_run").lower() != "live"
MAX_TRADE_USDC: float = float(os.environ.get("MAX_TRADE_USDC", "1.0"))
DAILY_MAX_LOSS_USDC: float = float(os.environ.get("DAILY_MAX_LOSS_USDC", "10.0"))
DIVERGENCE_THRESHOLD: float = float(os.environ.get("DIVERGENCE_THRESHOLD", "0.10"))
USE_RELATIVE_DIVERGENCE: bool = os.environ.get("USE_RELATIVE_DIVERGENCE", "false").lower() == "true"
TREND_THRESHOLD_PCT: float = float(os.environ.get("TREND_THRESHOLD_PCT", "0.001"))
OPPORTUNITY_PRICE_MAX: float = float(os.environ.get("OPPORTUNITY_PRICE_MAX", "0.20"))
TAKE_PROFIT_PRICE: float = float(os.environ.get("TAKE_PROFIT_PRICE", "0.40"))
LOOP_INTERVAL_SECS: float = float(os.environ.get("LOOP_INTERVAL_SECS", "1.0"))
DAILY_RESET_TZ_OFFSET: float = float(os.environ.get("DAILY_RESET_TZ_OFFSET_HOURS", "0.0"))
DB_PATH: Path = Path(os.environ.get("DB_PATH", "/data/trading_bot.db"))

FLATTEN_BEFORE_SETTLEMENT: bool = (
    os.environ.get("FLATTEN_BEFORE_SETTLEMENT", "true").lower() == "true"
)

# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------

_running = True


def _handle_signal(signum, frame) -> None:
    global _running
    logger.info("Received signal %d – shutting down gracefully", signum)
    _running = False


# ---------------------------------------------------------------------------
# DRY RUN order stub
# ---------------------------------------------------------------------------

_dry_run_counter = 0


def _dry_run_order(
    market_id: str,
    token_id: str,
    outcome: Outcome,
    side: Side,
    price: float,
    size_usdc: float,
) -> Order:
    global _dry_run_counter
    _dry_run_counter += 1
    return Order(
        order_id=f"DRY-{_dry_run_counter:04d}",
        market_id=market_id,
        token_id=token_id,
        outcome=outcome,
        side=side,
        price=price,
        size=size_usdc,
        status=OrderStatus.FILLED,
        filled_size=size_usdc,
        avg_fill_price=price,
        created_at=time.time(),
    )


# ---------------------------------------------------------------------------
# Core strategy helpers
# ---------------------------------------------------------------------------

def _place_order(
    client: PolymarketClient,
    market_id: str,
    token_id: str,
    outcome: Outcome,
    side: Side,
    price: float,
    size_usdc: float,
) -> Optional[Order]:
    if DRY_RUN:
        order = _dry_run_order(market_id, token_id, outcome, side, price, size_usdc)
        logger.info(
            "[DRY RUN] Would place order",
            extra={
                "order_id": order.order_id,
                "outcome": outcome.value,
                "side": side.value,
                "price": price,
                "size_usdc": size_usdc,
            },
        )
        return order
    try:
        order = client.place_limit_order(
            market_id=market_id,
            token_id=token_id,
            outcome=outcome,
            side=side,
            price=price,
            size_usdc=size_usdc,
        )
        logger.info(
            "Order placed",
            extra={
                "order_id": order.order_id,
                "outcome": outcome.value,
                "side": side.value,
                "price": price,
                "size_usdc": size_usdc,
            },
        )
        return order
    except Exception as exc:
        logger.error("Failed to place order: %s", exc)
        return None


def _sell_position(
    client: PolymarketClient,
    session: MarketSession,
    order: Order,
    current_book: OrderBook,
    label: str,
) -> None:
    """Sell an open position at the best available bid."""
    bid = current_book.best_bid
    if bid is None:
        logger.warning(
            "%s: No bids available to sell order %s", label, order.order_id
        )
        return

    sell_order = _place_order(
        client=client,
        market_id=session.market.market_id,
        token_id=order.token_id,
        outcome=order.outcome,
        side=Side.SELL,
        price=bid,
        size_usdc=order.size,
    )
    if sell_order:
        pnl = (bid - order.avg_fill_price) * order.size
        session.realised_pnl += pnl
        logger.info(
            "%s: Sold position, pnl=%.4f USDC", label, pnl,
            extra={"order_id": order.order_id, "bid": bid, "pnl": pnl},
        )


# ---------------------------------------------------------------------------
# Market cycle loop
# ---------------------------------------------------------------------------

def run_market_cycle(
    session: MarketSession,
    client: PolymarketClient,
    feed: BinanceFeed,
    risk: RiskManager,
    db: Database,
) -> None:
    """Run the full strategy loop for one 5-minute market."""

    logger.info(
        "Starting market cycle",
        extra={
            "market_id": session.market.market_id,
            "end": session.market.end_date_iso,
            "seconds_to_end": session.seconds_to_end,
        },
    )

    # Save config snapshot
    db.save_config(
        {
            "dry_run": DRY_RUN,
            "max_trade_usdc": MAX_TRADE_USDC,
            "daily_max_loss_usdc": DAILY_MAX_LOSS_USDC,
            "divergence_threshold": DIVERGENCE_THRESHOLD,
            "use_relative_divergence": USE_RELATIVE_DIVERGENCE,
            "trend_threshold_pct": TREND_THRESHOLD_PCT,
            "opportunity_price_max": OPPORTUNITY_PRICE_MAX,
            "take_profit_price": TAKE_PROFIT_PRICE,
            "flatten_before_settlement": FLATTEN_BEFORE_SETTLEMENT,
            "market_id": session.market.market_id,
        }
    )

    initial_trend: Optional[Trend] = None

    while _running and session.state not in (
        MarketState.EXITED,
    ):
        now = time.time()
        secs_left = session.market.end_timestamp - now

        # Market expired – exit
        if secs_left <= 0:
            logger.info("Market expired, exiting cycle")
            session.transition(MarketState.EXITED)
            break

        # Fetch order books
        try:
            book_up = client.get_order_book(session.market.token_id_up)
            book_down = client.get_order_book(session.market.token_id_down)
            risk.record_api_success()
        except Exception as exc:
            logger.warning("Order book fetch failed: %s", exc)
            risk.record_api_failure()
            if risk.is_halted:
                logger.error("Risk manager halted trading: %s", risk.halt_reason)
                break
            time.sleep(LOOP_INTERVAL_SECS)
            continue

        up_ask, down_ask = get_ask_prices(book_up, book_down)

        # ----------------------------------------------------------------
        # OBSERVE state: wait for price divergence + trend
        # ----------------------------------------------------------------
        if session.state == MarketState.OBSERVE:
            if up_ask is None or down_ask is None:
                time.sleep(LOOP_INTERVAL_SECS)
                continue

            if not is_diverged(
                up_ask, down_ask, DIVERGENCE_THRESHOLD, USE_RELATIVE_DIVERGENCE
            ):
                logger.debug(
                    "Prices close (up=%.4f down=%.4f), observing…",
                    up_ask, down_ask,
                )
                time.sleep(LOOP_INTERVAL_SECS)
                continue

            # Prices have diverged – check trend
            trend = get_trend(feed, TREND_THRESHOLD_PCT)
            if trend == Trend.NEUTRAL:
                logger.debug("Prices diverged but trend is NEUTRAL, waiting…")
                time.sleep(LOOP_INTERVAL_SECS)
                continue

            # Check risk limits
            allowed, reason = risk.can_enter(
                session.market.market_id, MAX_TRADE_USDC, secs_left
            )
            if not allowed:
                logger.info("Entry blocked: %s", reason)
                time.sleep(LOOP_INTERVAL_SECS)
                continue

            # Select token and entry price
            if trend == Trend.UP:
                token_id = session.market.token_id_up
                entry_price = up_ask
                outcome = Outcome.UP
            else:
                token_id = session.market.token_id_down
                entry_price = down_ask
                outcome = Outcome.DOWN

            order = _place_order(
                client, session.market.market_id, token_id,
                outcome, Side.BUY, entry_price, MAX_TRADE_USDC,
            )
            if order:
                session.initial_order = order
                session.initial_outcome = outcome
                session.initial_entry_price = entry_price
                initial_trend = trend
                risk.record_entry(session.market.market_id)
                db.upsert_order(order)
                session.transition(MarketState.ENTERED)

        # ----------------------------------------------------------------
        # ENTERED / OPPORTUNITY_BUY_DONE states: monitor positions
        # ----------------------------------------------------------------
        elif session.state in (
            MarketState.ENTERED,
            MarketState.OPPORTUNITY_BUY_DONE,
        ):
            # Check for FINAL MINUTE transition
            if secs_left <= 60 and session.state != MarketState.FINAL_MINUTE:
                session.transition(MarketState.FINAL_MINUTE)
                # Don't sleep – fall through to FINAL_MINUTE logic below
                continue

            # Check for trend reversal on initial position
            current_trend = get_trend(feed, TREND_THRESHOLD_PCT)
            if initial_trend and is_trend_reversal(initial_trend, current_trend):
                logger.info(
                    "Trend reversal detected (%s → %s), selling all positions",
                    initial_trend.value, current_trend.value,
                )
                if session.initial_order:
                    _sell_position(
                        client, session, session.initial_order, book_up
                        if session.initial_outcome == Outcome.UP else book_down,
                        "TrendReversal-Initial",
                    )
                if session.opportunity_order:
                    opp_book = (
                        book_up if session.opportunity_outcome == Outcome.UP
                        else book_down
                    )
                    _sell_position(
                        client, session, session.opportunity_order,
                        opp_book, "TrendReversal-Opportunity",
                    )
                session.transition(MarketState.EXITED)
                break

            # Check opportunity buy (only if we haven't done it yet)
            if (
                session.state == MarketState.ENTERED
                and session.has_opportunity_slot
                and secs_left > 60
            ):
                opp_ask: Optional[float] = None
                opp_outcome: Optional[Outcome] = None
                opp_token: Optional[str] = None

                if up_ask is not None and up_ask < OPPORTUNITY_PRICE_MAX:
                    opp_ask = up_ask
                    opp_outcome = Outcome.UP
                    opp_token = session.market.token_id_up
                elif down_ask is not None and down_ask < OPPORTUNITY_PRICE_MAX:
                    opp_ask = down_ask
                    opp_outcome = Outcome.DOWN
                    opp_token = session.market.token_id_down

                if opp_ask is not None and opp_outcome is not None and opp_token is not None:
                    allowed, reason = risk.can_enter(
                        session.market.market_id, MAX_TRADE_USDC, secs_left
                    )
                    if allowed:
                        opp_order = _place_order(
                            client, session.market.market_id, opp_token,
                            opp_outcome, Side.BUY, opp_ask, MAX_TRADE_USDC,
                        )
                        if opp_order:
                            session.opportunity_order = opp_order
                            session.opportunity_outcome = opp_outcome
                            session.opportunity_entry_price = opp_ask
                            risk.record_entry(session.market.market_id)
                            db.upsert_order(opp_order)
                            session.transition(MarketState.OPPORTUNITY_BUY_DONE)
                            logger.info(
                                "Opportunity buy placed at %.4f", opp_ask,
                                extra={"outcome": opp_outcome.value, "price": opp_ask},
                            )
                    else:
                        logger.debug("Opportunity entry blocked: %s", reason)

            # Check take-profit on opportunity position
            if session.opportunity_order and session.opportunity_outcome:
                opp_book = (
                    book_up if session.opportunity_outcome == Outcome.UP
                    else book_down
                )
                opp_mid = opp_book.mid
                if opp_mid is not None and opp_mid > TAKE_PROFIT_PRICE:
                    logger.info(
                        "Take-profit triggered on opportunity position "
                        "(mid=%.4f > %.4f)",
                        opp_mid, TAKE_PROFIT_PRICE,
                    )
                    _sell_position(
                        client, session, session.opportunity_order,
                        opp_book, "TakeProfit",
                    )
                    session.opportunity_order = None

        # ----------------------------------------------------------------
        # FINAL_MINUTE state
        # ----------------------------------------------------------------
        if session.state == MarketState.FINAL_MINUTE:
            if FLATTEN_BEFORE_SETTLEMENT:
                logger.info(
                    "Final minute: flattening all positions (FLATTEN_BEFORE_SETTLEMENT=true)"
                )
                if session.initial_order:
                    _sell_position(
                        client, session, session.initial_order,
                        book_up if session.initial_outcome == Outcome.UP else book_down,
                        "FinalMinute-Initial",
                    )
                if session.opportunity_order:
                    _sell_position(
                        client, session, session.opportunity_order,
                        book_up if session.opportunity_outcome == Outcome.UP else book_down,
                        "FinalMinute-Opportunity",
                    )
            else:
                # Check current trend confidence; hold if still aligned
                current_trend = get_trend(feed, TREND_THRESHOLD_PCT)
                if initial_trend and is_trend_reversal(initial_trend, current_trend):
                    logger.info("Final minute trend reversal – selling all")
                    if session.initial_order:
                        _sell_position(
                            client, session, session.initial_order,
                            book_up if session.initial_outcome == Outcome.UP else book_down,
                            "FinalMinute-Reversal-Initial",
                        )
                    if session.opportunity_order:
                        _sell_position(
                            client, session, session.opportunity_order,
                            book_up if session.opportunity_outcome == Outcome.UP else book_down,
                            "FinalMinute-Reversal-Opportunity",
                        )
                else:
                    logger.info("Final minute: trend consistent – holding to settlement")

            session.transition(MarketState.EXITED)

        time.sleep(LOOP_INTERVAL_SECS)

    # Record final PnL for this market
    # realised_pnl is positive for profits, negative for losses.
    # update_daily_loss expects a positive value representing a loss, so pass
    # the negated PnL (a positive loss becomes a negative PnL).
    if session.realised_pnl < 0:
        loss_amount = -session.realised_pnl  # convert negative PnL to positive loss
        risk.update_daily_loss(loss_amount)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    db.upsert_daily_pnl(today, -risk.daily_loss)

    risk.reset_market(session.market.market_id)
    logger.info(
        "Market cycle finished",
        extra={
            "market_id": session.market.market_id,
            "realised_pnl": session.realised_pnl,
        },
    )


# ---------------------------------------------------------------------------
# Top-level bot loop
# ---------------------------------------------------------------------------

def main() -> None:
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    if DRY_RUN:
        logger.warning(
            "=== DRY RUN MODE === Orders will NOT be placed on the exchange"
        )
    else:
        logger.warning(
            "=== LIVE TRADING MODE === Real money will be used. "
            "Ensure you understand the risks."
        )

    # Initialise components
    db = Database(DB_PATH)
    risk = RiskManager(
        limits=RiskLimits(
            max_trade_usdc=MAX_TRADE_USDC,
            daily_max_loss_usdc=DAILY_MAX_LOSS_USDC,
            daily_reset_tz_offset_hours=DAILY_RESET_TZ_OFFSET,
        )
    )

    # Price feeds
    binance_feed = BinanceFeed()
    chainlink_feed = ChainlinkFeed()
    binance_feed.start()
    chainlink_feed.start()

    # Polymarket client (only needed for live mode)
    client: Optional[PolymarketClient] = None
    if not DRY_RUN:
        try:
            client = PolymarketClient()
        except Exception as exc:
            logger.error("Failed to init Polymarket client: %s", exc)
            sys.exit(1)
    else:
        # In dry-run we still need the client for order book reads
        try:
            client = PolymarketClient()
        except Exception:
            logger.warning(
                "Polymarket client init failed in DRY RUN – order books unavailable"
            )
            client = None

    logger.info("Bot started. Waiting for price feed to warm up…")
    time.sleep(5)

    try:
        while _running:
            if risk.is_halted:
                logger.warning(
                    "Risk halted: %s – sleeping 60s", risk.halt_reason
                )
                time.sleep(60)
                continue

            # Discover the current/next market
            logger.info("Discovering active BTC 5m market…")
            import requests as _requests

            market_info = discover_active_market(session=_requests.Session())

            if client is None:
                # Dry run without a valid client – simulate market observation
                logger.info(
                    "[DRY RUN] Simulating market: %s", market_info.market_id
                )
                time.sleep(max(market_info.end_timestamp - time.time(), 1))
                continue

            session = MarketSession(market=market_info)
            run_market_cycle(
                session=session,
                client=client,
                feed=binance_feed,
                risk=risk,
                db=db,
            )

            # Brief pause between markets to avoid hammering the API
            if _running:
                gap = market_info.end_timestamp - time.time()
                if gap > 0:
                    logger.info("Waiting %.1fs for next market window…", gap)
                    time.sleep(min(gap + 2, 30))

    finally:
        binance_feed.stop()
        chainlink_feed.stop()
        db.close()
        logger.info("Bot shut down cleanly")


if __name__ == "__main__":
    main()
