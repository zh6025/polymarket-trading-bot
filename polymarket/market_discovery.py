"""Auto-rolling market discovery for BTC Up/Down 5-minute markets.

Discovers the currently active (or next upcoming) Polymarket 5-minute BTC
up/down market and transitions to successive markets automatically.

Discovery strategy
------------------
1. Query the Gamma API for events whose slug contains "btc-updown-5m".
2. Among the returned events, find the one whose end_date is in the future
   and whose start_date is in the past (i.e. currently active).
3. If no active market is found, wait and retry.
4. When a market expires, re-run discovery to find the next one.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import requests

from polymarket.endpoints import GAMMA_BASE_URL, GAMMA_EVENTS, GAMMA_MARKETS
from polymarket.models import MarketInfo

logger = logging.getLogger(__name__)

# Slug fragment that identifies these markets
BTC_5M_SLUG_FRAGMENT = "btc-updown-5m"

# How long to wait (seconds) between discovery retries
DISCOVERY_RETRY_INTERVAL = 10


def _parse_iso_to_ts(iso_str: str) -> float:
    """Parse an ISO-8601 datetime string to a Unix timestamp."""
    from datetime import datetime, timezone

    iso_str = iso_str.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(iso_str)
    except ValueError:
        # Some responses omit TZ info – assume UTC
        dt = datetime.fromisoformat(iso_str).replace(tzinfo=timezone.utc)
    return dt.timestamp()


def discover_active_market(session: Optional[requests.Session] = None) -> MarketInfo:
    """Discover the currently active BTC Up/Down 5m market.

    Blocks (with retries) until a market is found.
    """
    if session is None:
        session = requests.Session()

    while True:
        market = _try_discover(session)
        if market is not None:
            logger.info(
                "Discovered market",
                extra={"market_id": market.market_id, "end": market.end_date_iso},
            )
            return market
        logger.info(
            "No active 5m BTC market found, retrying in %ds", DISCOVERY_RETRY_INTERVAL
        )
        time.sleep(DISCOVERY_RETRY_INTERVAL)


def _try_discover(session: requests.Session) -> Optional[MarketInfo]:
    """Single attempt to discover the active market. Returns None on failure."""
    now = time.time()

    # Try Gamma events endpoint first
    try:
        url = f"{GAMMA_BASE_URL}{GAMMA_EVENTS}"
        resp = session.get(
            url,
            params={
                "slug": BTC_5M_SLUG_FRAGMENT,
                "active": "true",
                "limit": 20,
                "order": "end_date_asc",
            },
            timeout=15,
        )
        resp.raise_for_status()
        events = resp.json()
        if isinstance(events, dict):
            events = events.get("data", events.get("events", []))

        for event in events:
            mi = _parse_event(event, now)
            if mi is not None:
                return mi
    except Exception as exc:
        logger.warning("Gamma events lookup failed: %s", exc)

    # Fallback: query markets endpoint directly
    try:
        url = f"{GAMMA_BASE_URL}{GAMMA_MARKETS}"
        resp = session.get(
            url,
            params={
                "tag_slug": BTC_5M_SLUG_FRAGMENT,
                "active": "true",
                "limit": 20,
            },
            timeout=15,
        )
        resp.raise_for_status()
        markets_data = resp.json()
        if isinstance(markets_data, dict):
            markets_data = markets_data.get("data", markets_data.get("markets", []))

        for mkt in markets_data:
            mi = _parse_market(mkt, now)
            if mi is not None:
                return mi
    except Exception as exc:
        logger.warning("Gamma markets lookup failed: %s", exc)

    return None


def _parse_event(event: dict, now: float) -> Optional[MarketInfo]:
    """Try to build a MarketInfo from a Gamma event object."""
    slug = event.get("slug", "")
    if BTC_5M_SLUG_FRAGMENT not in slug:
        return None

    markets = event.get("markets", [])
    if not markets:
        return None

    # An event may have multiple market entries for each outcome
    token_id_up: Optional[str] = None
    token_id_down: Optional[str] = None
    end_date_iso = event.get("endDate", "")
    end_ts = _parse_iso_to_ts(end_date_iso) if end_date_iso else 0.0
    start_date_iso = event.get("startDate", "")
    start_ts = _parse_iso_to_ts(start_date_iso) if start_date_iso else 0.0

    # Must be currently active
    if now < start_ts or now > end_ts:
        return None

    market_id = event.get("conditionId", event.get("id", slug))

    for mkt in markets:
        outcome = (mkt.get("outcome") or mkt.get("outcomePrices") or "").upper()
        tid = mkt.get("clob_token_ids") or mkt.get("clobTokenIds") or []
        if isinstance(tid, list) and len(tid) == 2:
            token_id_up = tid[0]
            token_id_down = tid[1]
            break
        if "UP" in outcome or "YES" in outcome:
            token_id_up = mkt.get("conditionId", mkt.get("id", ""))
        elif "DOWN" in outcome or "NO" in outcome:
            token_id_down = mkt.get("conditionId", mkt.get("id", ""))

    if not token_id_up or not token_id_down:
        return None

    return MarketInfo(
        market_id=str(market_id),
        question=event.get("title", event.get("question", slug)),
        token_id_up=token_id_up,
        token_id_down=token_id_down,
        end_date_iso=end_date_iso,
        end_timestamp=end_ts,
        active=True,
        slug=slug,
    )


def _parse_market(mkt: dict, now: float) -> Optional[MarketInfo]:
    """Try to build a MarketInfo from a Gamma market object."""
    question = mkt.get("question", "")
    slug = mkt.get("slug", "")

    if BTC_5M_SLUG_FRAGMENT not in slug and "BTC" not in question.upper():
        return None

    end_date_iso = mkt.get("endDate", mkt.get("end_date", ""))
    end_ts = _parse_iso_to_ts(end_date_iso) if end_date_iso else 0.0
    start_date_iso = mkt.get("startDate", mkt.get("start_date", ""))
    start_ts = _parse_iso_to_ts(start_date_iso) if start_date_iso else 0.0

    if now < start_ts or now > end_ts:
        return None

    tid = mkt.get("clob_token_ids") or mkt.get("clobTokenIds") or []
    if isinstance(tid, list) and len(tid) == 2:
        token_id_up = tid[0]
        token_id_down = tid[1]
    else:
        return None

    market_id = mkt.get("conditionId", mkt.get("id", slug))

    return MarketInfo(
        market_id=str(market_id),
        question=question,
        token_id_up=token_id_up,
        token_id_down=token_id_down,
        end_date_iso=end_date_iso,
        end_timestamp=end_ts,
        active=True,
        slug=slug,
    )
