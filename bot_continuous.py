import json
import logging
import time
from typing import Optional, Tuple

import requests

from lib.config import load_config
from lib.data_persistence import DataPersistence
from lib.polymarket_client import PolymarketClient
from lib.risk_manager import RiskManager
from lib.trading_engine import BookLevel, OrderBookSnapshot, TradingEngine


def setup_logging(level: str) -> None:
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )


def to_snapshot(book: dict) -> OrderBookSnapshot:
    bids = book.get("bids", []) or []
    asks = book.get("asks", []) or []

    best_bid = None
    best_ask = None

    if bids:
        bid = bids[0]
        best_bid = BookLevel(price=float(bid["price"]), size=float(bid["size"]))

    if asks:
        ask = asks[0]
        best_ask = BookLevel(price=float(ask["price"]), size=float(ask["size"]))

    return OrderBookSnapshot(best_bid=best_bid, best_ask=best_ask)


def maybe_take_profit_or_stop(
    db: DataPersistence,
    risk: RiskManager,
    token_id: str,
    current_best_bid: Optional[float],
    profit_take_pct: float,
    stop_loss_pct: float,
) -> None:
    position = db.get_open_position(token_id)
    if not position or current_best_bid is None:
        return

    entry = position.entry_price
    change_pct = (current_best_bid - entry) / entry

    if change_pct >= profit_take_pct:
        realized = (current_best_bid - entry) * position.size
        db.record_trade(
            token_id=token_id,
            side="SELL",
            size=position.size,
            price=current_best_bid,
            realized_pnl=realized,
            reason="profit_take",
        )
        db.close_positions(token_id)
        risk.record_trade(realized_pnl=realized)
        logging.info("Closed %s for profit_take pnl=%.4f", token_id, realized)
        return

    if change_pct <= -stop_loss_pct:
        realized = (current_best_bid - entry) * position.size
        db.record_trade(
            token_id=token_id,
            side="SELL",
            size=position.size,
            price=current_best_bid,
            realized_pnl=realized,
            reason="stop_loss",
        )
        db.close_positions(token_id)
        risk.record_trade(realized_pnl=realized)
        logging.info("Closed %s for stop_loss pnl=%.4f", token_id, realized)


def _normalize_to_list(value):
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass
    return []


def extract_token_pair(event: dict) -> Tuple[str, str, str]:
    markets = event.get("markets", [])
    if not markets:
        raise ValueError("event.markets is empty")

    market = markets[0]
    condition_id = market.get("conditionId") or market.get("condition_id") or ""

    outcomes = _normalize_to_list(market.get("outcomes"))
    clob_token_ids = _normalize_to_list(market.get("clobTokenIds"))

    if len(outcomes) == 2 and len(clob_token_ids) == 2:
        mapping = dict(zip(outcomes, clob_token_ids))
        yes_token = mapping.get("Up")
        no_token = mapping.get("Down")
        if yes_token and no_token:
            return condition_id, yes_token, no_token

    tokens = market.get("tokens")
    if isinstance(tokens, list) and len(tokens) == 2:
        outcome_to_token = {}
        for t in tokens:
            if not isinstance(t, dict):
                continue
            outcome = t.get("outcome") or t.get("name") or t.get("label")
            token_id = t.get("token_id") or t.get("tokenId") or t.get("asset_id") or t.get("id")
            if outcome and token_id:
                outcome_to_token[str(outcome)] = str(token_id)

        yes_token = outcome_to_token.get("Up")
        no_token = outcome_to_token.get("Down")
        if yes_token and no_token:
            return condition_id, yes_token, no_token

    raise ValueError(
        f"Invalid market outcomes/clobTokenIds structure: "
        f"outcomes={market.get('outcomes')} clobTokenIds={market.get('clobTokenIds')} tokens={market.get('tokens')}"
    )


def discover_current_market(client: PolymarketClient) -> Tuple[str, str, str, str]:
    event = client.get_current_btc_5m_market()
    if not event:
        raise RuntimeError("No active BTC 5m market found")

    title = event.get("title", "")
    slug = event.get("slug", "")
    condition_id, yes_token_id, no_token_id = extract_token_pair(event)

    logging.info(
        "Discovered active market slug=%s title=%s condition_id=%s",
        slug,
        title,
        condition_id,
    )
    logging.info("Resolved tokens: Up=%s Down=%s", yes_token_id, no_token_id)

    return slug, condition_id, yes_token_id, no_token_id


def is_not_found_error(exc: Exception) -> bool:
    return isinstance(exc, requests.exceptions.HTTPError) and exc.response is not None and exc.response.status_code == 404


def main() -> None:
    config = load_config()
    setup_logging(config.log_level)

    client = PolymarketClient(
        host=config.host,
        chain_id=config.chain_id,
        private_key=config.private_key,
        proxy_address=config.proxy_address,
    )

    risk = RiskManager(
        max_position_size=config.max_position_size,
        max_daily_loss=config.max_daily_loss,
        max_trades_per_day=config.max_trades_per_day,
        cooldown_seconds=config.cooldown_seconds,
    )

    engine = TradingEngine(
        min_order_size=config.min_order_size,
        imbalance_threshold=config.imbalance_threshold,
        min_spread=config.min_spread,
    )

    db = DataPersistence(config.db_path)

    current_slug = ""
    current_condition_id = ""
    yes_token_id = ""
    no_token_id = ""

    logging.info("Bot started. dry_run=%s", config.dry_run)

    while True:
        try:
            if not yes_token_id or not no_token_id:
                current_slug, current_condition_id, yes_token_id, no_token_id = discover_current_market(client)

            yes_book_raw = client.get_order_book(yes_token_id)
            no_book_raw = client.get_order_book(no_token_id)

            yes_book = to_snapshot(yes_book_raw)
            no_book = to_snapshot(no_book_raw)

            maybe_take_profit_or_stop(
                db=db,
                risk=risk,
                token_id=yes_token_id,
                current_best_bid=yes_book.best_bid.price if yes_book.best_bid else None,
                profit_take_pct=config.profit_take_pct,
                stop_loss_pct=config.stop_loss_pct,
            )

            maybe_take_profit_or_stop(
                db=db,
                risk=risk,
                token_id=no_token_id,
                current_best_bid=no_book.best_bid.price if no_book.best_bid else None,
                profit_take_pct=config.profit_take_pct,
                stop_loss_pct=config.stop_loss_pct,
            )

            signal = engine.evaluate(yes_book, no_book)
            if signal is None:
                time.sleep(config.orderbook_poll_seconds)
                continue

            token_id = yes_token_id if signal.should_buy_yes else no_token_id
            current_position = db.get_open_position(token_id)
            current_position_size = current_position.size if current_position else 0.0

            decision = risk.can_open_position(
                current_position_size=current_position_size,
                new_order_size=signal.order_size,
            )

            if not decision.allowed:
                logging.info("Trade skipped: %s", decision.reason)
                time.sleep(config.orderbook_poll_seconds)
                continue

            side = "BUY"
            if config.dry_run:
                logging.info(
                    "[DRY RUN] %s %s size=%.4f price=%.4f reason=%s market_slug=%s",
                    side,
                    token_id,
                    signal.order_size,
                    signal.target_price,
                    signal.reason,
                    current_slug,
                )
            else:
                client.place_order(
                    token_id=token_id,
                    side=side,
                    price=signal.target_price,
                    size=signal.order_size,
                )

            db.add_position(
                token_id=token_id,
                side=side,
                size=signal.order_size,
                entry_price=signal.target_price,
            )
            db.record_trade(
                token_id=token_id,
                side=side,
                size=signal.order_size,
                price=signal.target_price,
                realized_pnl=0.0,
                reason=signal.reason,
            )
            risk.record_trade(realized_pnl=0.0)

            logging.info(
                "Opened %s size=%.4f price=%.4f reason=%s market_slug=%s",
                token_id,
                signal.order_size,
                signal.target_price,
                signal.reason,
                current_slug,
            )

        except KeyboardInterrupt:
            logging.info("Bot stopped by user")
            break
        except Exception as exc:
            if is_not_found_error(exc):
                logging.warning("Orderbook returned 404. Refreshing active market discovery.")
                yes_token_id = ""
                no_token_id = ""
                current_slug = ""
                current_condition_id = ""
            else:
                logging.exception("Main loop error: %s", exc)

        time.sleep(config.orderbook_poll_seconds)


if __name__ == "__main__":
    main()
