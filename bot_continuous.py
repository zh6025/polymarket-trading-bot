#!/usr/bin/env python3
"""
Continuous polling loop for the Polymarket BTC 5m market-making bot.

Runs indefinitely, refreshing the active market every ~5 minutes and
placing market-making orders on each poll tick.
"""

import os
import asyncio
import json
import re
import logging
from datetime import datetime, timezone
from typing import Dict, Optional

from lib.config import load_config
from lib.polymarket_client import PolymarketClient
from lib.trading_engine import TradingEngine, BookLevel, OrderBookSnapshot
from lib.data_persistence import DataPersistence
from lib.risk_manager import RiskManager
from lib.utils import log_info, log_error, log_warn

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
)

BANNER = """
╔══════════════════════════════════════════════════════╗
║    Polymarket BTC 5m Bot — Continuous Loop           ║
╚══════════════════════════════════════════════════════╝"""


class MarketExpiredError(Exception):
    """Raised when a market token returns 404 (market has settled)."""


def _parse_book(raw: dict) -> OrderBookSnapshot:
    """Convert a raw CLOB order-book dict to an OrderBookSnapshot."""
    bids = raw.get("bids", [])
    asks = raw.get("asks", [])
    best_bid = BookLevel(float(bids[-1]["price"]), float(bids[-1]["size"])) if bids else None
    best_ask = BookLevel(float(asks[-1]["price"]), float(asks[-1]["size"])) if asks else None
    return OrderBookSnapshot(best_bid=best_bid, best_ask=best_ask)


class ContinuousBot:
    """Market-making bot that polls the order book and places orders."""

    def __init__(self, config):
        self.config = config
        self.dry_run = config.dry_run

        self.client = PolymarketClient(
            host=config.host,
            chain_id=config.chain_id,
            private_key=config.private_key,
            proxy_address=config.proxy_address,
        )
        self.engine = TradingEngine(
            min_order_size=config.min_order_size,
            imbalance_threshold=config.imbalance_threshold,
            min_spread=config.min_spread,
            dry_run=config.dry_run,
        )
        self.db = DataPersistence(config.db_path)
        self.risk = RiskManager(
            max_position_size=config.max_position_size,
            max_daily_loss=config.max_daily_loss,
            max_trades_per_day=config.max_trades_per_day,
            cooldown_seconds=config.cooldown_seconds,
        )

        self.poll_interval = config.orderbook_poll_seconds
        self.total_cycles = 0

    # ── Market discovery ─────────────────────────────────────────────────────

    def find_active_market(self) -> Optional[Dict]:
        """Return a dict describing the current BTC 5m market, or None."""
        event = self.client.get_current_btc_5m_market()
        if not event:
            return None

        for m in event.get("markets", []):
            if not m.get("acceptingOrders", False) or m.get("closed", False):
                continue
            raw = m.get("clobTokenIds", "[]")
            token_ids = json.loads(raw) if isinstance(raw, str) else raw
            if len(token_ids) < 2:
                continue
            return {
                "title": event.get("title", ""),
                "slug": event.get("slug", ""),
                "question": m.get("question", ""),
                "up_token": token_ids[0],
                "down_token": token_ids[1],
                "tick_size": float(m.get("orderPriceMinTickSize", 0.01)),
                "min_size": float(m.get("orderMinSize", self.config.min_order_size)),
            }
        return None

    def _market_start_ts(self, market: Dict) -> Optional[int]:
        slug = market.get("slug", "") or market.get("title", "")
        match = re.search(r"btc-updown-5m-(\d+)", slug)
        return int(match.group(1)) if match else None

    # ── Order-book helpers ───────────────────────────────────────────────────

    def _fetch_books(self, market: Dict) -> tuple:
        """Return (up_book_raw, down_book_raw) or raise MarketExpiredError."""
        try:
            up_raw = self.client.get_orderbook(market["up_token"])
            down_raw = self.client.get_orderbook(market["down_token"])
            return up_raw, down_raw
        except Exception as exc:
            if "404" in str(exc) or "Not Found" in str(exc):
                raise MarketExpiredError(f"Token expired (404): {exc}") from exc
            raise

    def _get_mid(self, raw_book: dict) -> Dict:
        return self.client.calculate_mid_price(raw_book)

    # ── Trade execution ──────────────────────────────────────────────────────

    def _maybe_trade(self, market: Dict, up_raw: dict, down_raw: dict) -> None:
        """Evaluate books and place orders if the signal is positive."""
        up_snap = _parse_book(up_raw)
        down_snap = _parse_book(down_raw)

        signal = self.engine.evaluate(up_snap, down_snap)
        if signal is None:
            log_info("No signal this tick")
            return

        token_id = market["up_token"] if signal.should_buy_yes else market["down_token"]
        side_label = "UP" if signal.should_buy_yes else "DOWN"

        existing_pos = self.db.get_open_position(token_id)
        current_size = existing_pos.size if existing_pos else 0.0

        risk_result = self.risk.can_open_position(current_size, signal.order_size)
        if not risk_result.allowed:
            log_warn(f"Risk blocked trade: {risk_result.reason}")
            return

        log_info(f"Signal: BUY {side_label} @ {signal.target_price:.4f} x {signal.order_size} — {signal.reason}")

        if self.dry_run:
            log_info(f"[DRY-RUN] Skipping real order placement")
        else:
            result = self.client.place_order(token_id, "buy", signal.target_price, signal.order_size)
            if result is None:
                log_error("Order placement failed")
                return

        self.db.add_position(token_id, "buy", signal.target_price, signal.order_size)
        self.db.record_trade(
            token_id=token_id,
            side="buy",
            price=signal.target_price,
            size=signal.order_size,
        )
        self.risk.record_trade(realized_pnl=0.0)

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def run(self) -> None:
        print(BANNER)
        mode = "🟡 DRY-RUN (no real orders)" if self.dry_run else "🔴 LIVE TRADING"
        print(f"Mode: {mode}\n")

        current_market: Optional[Dict] = None
        market_start_ts: Optional[int] = None

        while True:
            try:
                now_ts = int(datetime.now(tz=timezone.utc).timestamp())

                # Refresh market every ~290s (10s before expiry)
                need_refresh = (
                    current_market is None
                    or market_start_ts is None
                    or (now_ts - market_start_ts) >= 290
                )

                if need_refresh:
                    print(f"\n{'='*60}")
                    log_info("Looking for active BTC 5m market…")
                    new_market = self.find_active_market()
                    if new_market:
                        current_market = new_market
                        market_start_ts = self._market_start_ts(new_market) or now_ts
                        self.total_cycles += 1
                        elapsed = now_ts - market_start_ts
                        log_info(
                            f"Cycle #{self.total_cycles}: {current_market['title']} "
                            f"(+{elapsed}s elapsed)"
                        )
                    else:
                        log_warn("No active market — retrying in 10s")
                        await asyncio.sleep(10)
                        continue

                # Fetch books
                try:
                    up_raw, down_raw = self._fetch_books(current_market)
                except MarketExpiredError as exc:
                    log_warn(f"Market settled — forcing refresh: {exc}")
                    current_market = None
                    market_start_ts = None
                    await asyncio.sleep(5)
                    continue
                except Exception as exc:
                    log_error(f"Order book fetch error: {exc}")
                    await asyncio.sleep(self.poll_interval)
                    continue

                up_mid = self._get_mid(up_raw)
                down_mid = self._get_mid(down_raw)
                elapsed = now_ts - (market_start_ts or now_ts)

                if up_mid["mid"] is not None and down_mid["mid"] is not None:
                    print(
                        f"[{datetime.now().strftime('%H:%M:%S')}] +{elapsed}s "
                        f"UP={up_mid['mid']:.4f} DOWN={down_mid['mid']:.4f}"
                    )
                    self._maybe_trade(current_market, up_raw, down_raw)
                else:
                    log_warn("Incomplete order book — skipping tick")

                await asyncio.sleep(self.poll_interval)

            except KeyboardInterrupt:
                print("\n🛑 Interrupted by user")
                break
            except Exception as exc:
                log_error(f"Main loop error: {exc}")
                import traceback
                traceback.print_exc()
                await asyncio.sleep(10)

        self.db.close()


async def main() -> None:
    config = load_config()
    bot = ContinuousBot(config)
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
