#!/usr/bin/env python3
import sys
import time
import json
import logging
from typing import Dict, Any, Optional, Tuple

from lib.config import load_config
from lib.utils import log_info, log_error, log_warn
from lib.polymarket_client import PolymarketClient
from lib.risk import RiskManager
from lib.strategy import ProductionDecisionStrategy
from lib.bot_state import (
    load_state,
    save_state,
    reset_daily_if_needed,
    record_trade_open,
)

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def parse_book_top(book: Dict[str, Any]) -> Dict[str, float]:
    bids = book.get("bids", []) or []
    asks = book.get("asks", []) or []

    if not bids or not asks:
        return {
            "bid_price": 0.0,
            "bid_size": 0.0,
            "ask_price": 0.0,
            "ask_size": 0.0,
            "spread": 1.0,
            "mid": 0.5,
            "depth_usdc": 0.0,
        }

    best_bid = bids[0]
    best_ask = asks[0]

    bid_price = float(best_bid.get("price", 0.0))
    ask_price = float(best_ask.get("price", 0.0))
    bid_size = float(best_bid.get("size", 0.0))
    ask_size = float(best_ask.get("size", 0.0))

    spread = ask_price - bid_price
    mid = (bid_price + ask_price) / 2 if (bid_price > 0 and ask_price > 0) else 0.5

    bid_depth_usdc = bid_price * bid_size
    ask_depth_usdc = ask_price * ask_size
    depth_usdc = min(bid_depth_usdc, ask_depth_usdc)

    return {
        "bid_price": bid_price,
        "bid_size": bid_size,
        "ask_price": ask_price,
        "ask_size": ask_size,
        "spread": spread,
        "mid": mid,
        "depth_usdc": depth_usdc,
    }


def infer_remaining_sec_from_slug(slug: str, now_ts: int) -> Optional[int]:
    try:
        ts = int(slug.rsplit("-", 1)[-1])
        end_ts = ts + 300
        return max(end_ts - now_ts, 0)
    except Exception:
        return None


def _normalize_token_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "token_id": entry.get("token_id") or entry.get("tokenId") or entry.get("clobTokenId") or "",
        "outcome": str(entry.get("outcome", "")).upper(),
    }


def select_tokens(market: Dict[str, Any]) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
    tokens = market.get("tokens", [])

    normalized = []
    if isinstance(tokens, list) and len(tokens) >= 2:
        for t in tokens:
            if isinstance(t, dict):
                normalized.append(_normalize_token_entry(t))

    if len(normalized) >= 2:
        yes_token = None
        no_token = None

        for t in normalized:
            outcome = t.get("outcome", "")
            if outcome in ("YES", "UP"):
                yes_token = t
            elif outcome in ("NO", "DOWN"):
                no_token = t

        if yes_token and no_token:
            return yes_token, no_token

        if normalized[0].get("token_id") and normalized[1].get("token_id"):
            return normalized[0], normalized[1]

    raw_ids = market.get("clobTokenIds", [])
    try:
        if isinstance(raw_ids, str):
            raw_ids = json.loads(raw_ids)
    except Exception:
        raw_ids = []

    if isinstance(raw_ids, list) and len(raw_ids) >= 2:
        yes_token = {"token_id": str(raw_ids[0]), "outcome": "YES"}
        no_token = {"token_id": str(raw_ids[1]), "outcome": "NO"}
        return yes_token, no_token

    return None


def estimate_win_prob(yes_mid: float, no_mid: float) -> float:
    total = yes_mid + no_mid
    if total <= 0:
        return 0.5
    p = yes_mid / total
    return max(0.01, min(0.99, p))


def maybe_place_order(
    client: PolymarketClient,
    dry_run: bool,
    token_id: str,
    side: str,
    price: float,
    size: float,
) -> Dict[str, Any]:
    if dry_run:
        log_info(
            f"[DRY_RUN] place_order token_id={token_id} side={side} price={price:.4f} size={size:.2f}"
        )
        return {
            "status": "dry_run",
            "token_id": token_id,
            "side": side,
            "price": price,
            "size": size,
        }

    return client.place_order(
        token_id=token_id,
        side=side,
        price=price,
        size=size,
    )


def main():
    print("""
╔══════════════════════════════════════════════════════════════╗
║   Polymarket Trading Bot - Production Decision Runner       ║
║          BTC Up/Down 5 Minute Markets (Safe Mode)           ║
╚══════════════════════════════════════════════════════════════╝
    """)

    try:
        config = load_config()

        log_info(
            f"Bot starting | dry_run={config.dry_run} trading_enabled={config.trading_enabled} "
            f"state_file={config.state_file_path}"
        )

        client = PolymarketClient(
            host=config.host,
            chain_id=config.chain_id,
            private_key=config.private_key,
            proxy_address=config.proxy_address,
        )

        risk = RiskManager(config)
        strategy = ProductionDecisionStrategy(config)

        state = load_state(
            file_path=config.state_file_path,
            trading_enabled=config.trading_enabled,
        )

        now_ts = int(time.time())
        reset_daily_if_needed(state, now_ts)
        save_state(state, config.state_file_path)

        event = client.get_current_btc_5m_market()
        if not event:
            log_warn("No active BTC 5m market found")
            print("⚠️ 未找到当前可交易的 BTC 5 分钟市场")
            return

        event_title = event.get("title", "")
        log_info(f"Selected event: {event_title}")

        markets = event.get("markets", [])
        active_markets = [
            m for m in markets
            if m.get("acceptingOrders", False) and not m.get("closed", True)
        ]

        if not active_markets:
            log_warn("No accepting active markets inside event")
            print("⚠️ 当前事件里没有可接受订单的市场")
            return

        market = active_markets[0]
        market_id = market.get("conditionId", "") or market.get("slug", "") or market.get("question", "unknown-market")
        market_slug = market.get("slug", event.get("slug", ""))
        market_question = market.get("question", event_title)

        remaining_sec = infer_remaining_sec_from_slug(market_slug, now_ts)
        if remaining_sec is None:
            log_warn(f"Unable to infer remaining seconds from slug={market_slug}")
            remaining_sec = 999

        selected = select_tokens(market)
        if not selected:
            log_warn(f"Market has invalid tokens structure | market keys={list(market.keys())}")
            log_warn(f"Market raw snippet: {str(market)[:1000]}")
            print("⚠️ 市场 tokens 结构异常")
            return

        yes_token, no_token = selected
        yes_token_id = yes_token.get("token_id")
        no_token_id = no_token.get("token_id")

        if not yes_token_id or not no_token_id:
            log_warn("Missing yes/no token ids")
            print("⚠️ token_id 缺失")
            return

        yes_book = client.get_orderbook(yes_token_id)
        no_book = client.get_orderbook(no_token_id)

        yes_top = parse_book_top(yes_book)
        no_top = parse_book_top(no_book)

        yes_bid = yes_top["bid_price"]
        yes_ask = yes_top["ask_price"]
        yes_spread = yes_top["spread"]
        yes_mid = yes_top["mid"]
        yes_depth = yes_top["depth_usdc"]

        no_bid = no_top["bid_price"]
        no_ask = no_top["ask_price"]
        no_spread = no_top["spread"]
        no_mid = no_top["mid"]
        no_depth = no_top["depth_usdc"]

        win_prob_yes = estimate_win_prob(yes_mid, no_mid)
        win_prob_no = 1.0 - win_prob_yes

        print("\n" + "=" * 72)
        print("📊 Market Snapshot")
        print("=" * 72)
        print(f"Question        : {market_question}")
        print(f"Market ID       : {market_id}")
        print(f"Slug            : {market_slug}")
        print(f"Remaining Sec   : {remaining_sec}")
        print(f"YES bid/ask/mid : {yes_bid:.4f} / {yes_ask:.4f} / {yes_mid:.4f}")
        print(f"YES spread/depth: {yes_spread:.4f} / {yes_depth:.2f}")
        print(f"NO  bid/ask/mid : {no_bid:.4f} / {no_ask:.4f} / {no_mid:.4f}")
        print(f"NO  spread/depth: {no_spread:.4f} / {no_depth:.2f}")
        print(f"P(YES) approx   : {win_prob_yes:.4f}")
        print(f"P(NO)  approx   : {win_prob_no:.4f}")
        print("=" * 72)

        candidates = [
            {
                "name": "YES",
                "main_outcome": "YES",
                "main_token_id": yes_token_id,
                "main_price": yes_ask,
                "main_spread": yes_spread,
                "main_depth": yes_depth,
                "hedge_outcome": "NO",
                "hedge_token_id": no_token_id,
                "hedge_price": no_ask,
                "hedge_spread": no_spread,
                "hedge_depth": no_depth,
                "win_prob": win_prob_yes,
            },
            {
                "name": "NO",
                "main_outcome": "NO",
                "main_token_id": no_token_id,
                "main_price": no_ask,
                "main_spread": no_spread,
                "main_depth": no_depth,
                "hedge_outcome": "YES",
                "hedge_token_id": yes_token_id,
                "hedge_price": yes_ask,
                "hedge_spread": yes_spread,
                "hedge_depth": yes_depth,
                "win_prob": win_prob_no,
            },
        ]

        best = None
        for c in candidates:
            if best is None or c["win_prob"] > best["win_prob"]:
                best = c

        if not best:
            log_warn("No candidate selected")
            print("⚠️ 无候选方向")
            return

        if state.market_has_position(market_id):
            log_warn(f"Skip market because already open in state: {market_id}")
            print(f"⛔ 已有持仓，跳过 market_id={market_id}")
            return

        current_pnl = state.daily_realized_pnl_usdc

        global_risk_ok = risk.check_global_risk(
            market_id=market_id,
            current_pnl=current_pnl,
            now_ts=now_ts,
        )

        if not global_risk_ok:
            print("⛔ Global risk check failed")
            if not config.dry_run:
                save_state(state, config.state_file_path)
                return
            print("🧪 DRY_RUN mode: continue to evaluate strategy without placing live orders")

        decision = strategy.decide(
            main_price=best["main_price"],
            hedge_price=best["hedge_price"],
            win_prob=best["win_prob"],
            remaining_sec=remaining_sec,
            main_spread=best["main_spread"],
            hedge_spread=best["hedge_spread"],
            main_depth_usdc=best["main_depth"],
            hedge_depth_usdc=best["hedge_depth"],
            main_size_usdc=config.min_order_size,
        )

        print("\n" + "=" * 72)
        print("🧠 Decision")
        print("=" * 72)
        print(f"Direction       : {best['main_outcome']}")
        print(f"Decision        : {decision.decision}")
        print(f"Reason          : {decision.decision_reason}")
        print(f"Win Prob        : {best['win_prob']:.4f}")
        print(f"Main Price      : {best['main_price']:.4f}")
        print(f"Hedge Price     : {best['hedge_price']:.4f}")
        print(f"Hedge Ratio     : {decision.hedge_ratio:.4f}")
        print(f"Main Size       : {decision.main_size:.2f}")
        print(f"Hedge Size      : {decision.hedge_size:.2f}")
        print(f"Skip Reasons    : {decision.skip_reasons}")
        print("=" * 72)

        log_info(
            f"Decision summary | market_id={market_id} direction={best['main_outcome']} "
            f"decision={decision.decision} reason={decision.decision_reason} "
            f"remaining_sec={remaining_sec} win_prob={best['win_prob']:.4f}"
        )

        if decision.decision == "SKIP":
            save_state(state, config.state_file_path)
            print("✅ 已跳过，不下单")
            return

        main_result = maybe_place_order(
            client=client,
            dry_run=True if config.dry_run else (not config.trading_enabled),
            token_id=best["main_token_id"],
            side="buy",
            price=best["main_price"],
            size=decision.main_size,
        )

        hedge_result = None
        if decision.should_trade_hedge and decision.hedge_size > 0:
            hedge_result = maybe_place_order(
                client=client,
                dry_run=True if config.dry_run else (not config.trading_enabled),
                token_id=best["hedge_token_id"],
                side="buy",
                price=best["hedge_price"],
                size=decision.hedge_size,
            )

        record_trade_open(
            state=state,
            market_id=market_id,
            now_ts=now_ts,
            main_outcome=best["main_outcome"],
            main_token_id=best["main_token_id"],
            main_price=best["main_price"],
            main_size=decision.main_size,
            hedge_outcome=best["hedge_outcome"] if decision.should_trade_hedge else None,
            hedge_token_id=best["hedge_token_id"] if decision.should_trade_hedge else None,
            hedge_price=best["hedge_price"] if decision.should_trade_hedge else 0.0,
            hedge_size=decision.hedge_size if decision.should_trade_hedge else 0.0,
        )

        save_state(state, config.state_file_path)

        print("\n" + "=" * 72)
        print("📝 Order Result")
        print("=" * 72)
        print(f"Main Order      : {main_result}")
        print(f"Hedge Order     : {hedge_result}")
        print(f"State Saved     : {config.state_file_path}")
        print("=" * 72)

        log_info("✅ bot_runner completed")

    except Exception as e:
        log_error(f"❌ Fatal error: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
