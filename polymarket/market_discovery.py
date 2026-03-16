"""Auto-rolling market discovery for BTC Up/Down 5-minute markets.

Discovers the currently active (or next upcoming) Polymarket 5-minute BTC
up/down market and transitions to successive markets automatically.

Discovery strategy
------------------
The BTC Up/Down 5-minute markets follow a predictable naming scheme:

    slug = "btc-updown-5m-{end_timestamp}"

where ``end_timestamp`` is a Unix timestamp aligned to a 5-minute (300 s)
boundary.  For example, for a market ending at 2026-03-13 17:10:00 UTC the
slug is ``btc-updown-5m-1773288600``.

This module uses two complementary strategies, in order:

1. **Timestamp derivation** – compute the expected slug for the current and
   adjacent 5-minute windows and fetch them directly via a targeted Gamma
   ``/events?slug=`` query.  Fast and reliable.

2. **Active-market scan** – if the direct lookup fails, fetch the most recent
   active events and filter by slug prefix.  Handles edge cases such as early
   market opening or delayed API propagation.

Parsing note
------------
The Gamma API returns array fields such as ``clobTokenIds`` and ``outcomes``
as **JSON-encoded strings**, not raw JSON arrays.  All parsing helpers in
this module call :func:`_decode_json_field` to handle both formats.
"""
from __future__ import annotations

import json
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

# How many 5-minute windows ahead/behind to search during timestamp derivation
_WINDOW_SEARCH_RANGE = 2


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

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


def _decode_json_field(value) -> list:
    """Decode a field that may be a JSON-encoded string or a plain list.

    The Gamma API returns fields such as ``clobTokenIds`` and ``outcomes``
    as JSON-encoded strings (e.g. ``'["abc","def"]'``).  This helper
    normalises both representations to a plain Python list.

    >>> _decode_json_field('["a", "b"]')
    ['a', 'b']
    >>> _decode_json_field(['a', 'b'])
    ['a', 'b']
    >>> _decode_json_field(None)
    []
    """
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, ValueError):
            return [value] if value else []
    return []


def _candidate_window_ends(now: float) -> list[int]:
    """Return a list of candidate window-end timestamps near *now*.

    The current window's end is ``((now // 300) + 1) * 300``.  We also
    include one window behind and ahead to handle clock skew or markets that
    have just closed/opened.
    """
    base = int((now // 300 + 1) * 300)
    return [base + i * 300 for i in range(-_WINDOW_SEARCH_RANGE, _WINDOW_SEARCH_RANGE + 1)]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def discover_active_market(session: Optional[requests.Session] = None) -> MarketInfo:
    """Discover the currently active BTC Up/Down 5m market.

    Blocks (with retries at :data:`DISCOVERY_RETRY_INTERVAL`-second intervals)
    until a market is found.
    """
    if session is None:
        session = requests.Session()

    while True:
        market = _try_discover(session)
        if market is not None:
            logger.info(
                "Discovered market: %s (ends %s)",
                market.market_id,
                market.end_date_iso,
            )
            return market
        logger.info(
            "No active 5m BTC market found, retrying in %ds",
            DISCOVERY_RETRY_INTERVAL,
        )
        time.sleep(DISCOVERY_RETRY_INTERVAL)


# ---------------------------------------------------------------------------
# Private discovery logic
# ---------------------------------------------------------------------------

def _try_discover(session: requests.Session) -> Optional[MarketInfo]:
    """Single attempt.  Returns None on any failure or no active market."""
    now = time.time()

    # Strategy 1: direct slug lookup using derived timestamps
    for window_end in _candidate_window_ends(now):
        slug = f"{BTC_5M_SLUG_FRAGMENT}-{window_end}"
        market = _fetch_event_by_slug(session, slug, now)
        if market is not None:
            return market

    # Strategy 2: scan recent active events and filter client-side
    return _scan_active_events(session, now)


def _fetch_event_by_slug(
    session: requests.Session, slug: str, now: float
) -> Optional[MarketInfo]:
    """Fetch a single event by exact slug from the Gamma API."""
    try:
        url = f"{GAMMA_BASE_URL}{GAMMA_EVENTS}"
        resp = session.get(
            url,
            params={"slug": slug},
            timeout=15,
        )
        resp.raise_for_status()
        events = resp.json()

        # Gamma /events returns a list directly or a dict with a data key
        if isinstance(events, dict):
            events = events.get("data", events.get("events", []))
        if not isinstance(events, list):
            return None

        for event in events:
            mi = _parse_event(event, now)
            if mi is not None:
                return mi
    except Exception as exc:
        logger.debug("Gamma slug lookup failed for %s: %s", slug, exc)
    return None


def _scan_active_events(session: requests.Session, now: float) -> Optional[MarketInfo]:
    """Scan recent active Gamma events and filter for BTC 5m markets."""
    try:
        url = f"{GAMMA_BASE_URL}{GAMMA_EVENTS}"
        resp = session.get(
            url,
            params={
                "active": "true",
                "archived": "false",
                "closed": "false",
                "limit": 50,
            },
            timeout=15,
        )
        resp.raise_for_status()
        events = resp.json()
        if isinstance(events, dict):
            events = events.get("data", events.get("events", []))
        if not isinstance(events, list):
            return None

        for event in events:
            if BTC_5M_SLUG_FRAGMENT not in event.get("slug", ""):
                continue
            mi = _parse_event(event, now)
            if mi is not None:
                return mi
    except Exception as exc:
        logger.warning("Gamma active-event scan failed: %s", exc)

    # Final fallback: markets endpoint
    return _scan_active_markets(session, now)


def _scan_active_markets(session: requests.Session, now: float) -> Optional[MarketInfo]:
    """Query the /markets endpoint as a last resort."""
    try:
        url = f"{GAMMA_BASE_URL}{GAMMA_MARKETS}"
        resp = session.get(
            url,
            params={
                "active": "true",
                "closed": "false",
                "archived": "false",
                "limit": 50,
            },
            timeout=15,
        )
        resp.raise_for_status()
        markets_data = resp.json()
        if isinstance(markets_data, dict):
            markets_data = markets_data.get("data", markets_data.get("markets", []))
        if not isinstance(markets_data, list):
            return None

        for mkt in markets_data:
            mi = _parse_standalone_market(mkt, now)
            if mi is not None:
                return mi
    except Exception as exc:
        logger.warning("Gamma markets scan failed: %s", exc)
    return None


# ---------------------------------------------------------------------------
# Response parsers
# ---------------------------------------------------------------------------

def _parse_event(event: dict, now: float) -> Optional[MarketInfo]:
    """Build a :class:`~polymarket.models.MarketInfo` from a Gamma event dict.

    Handles the Gamma API's convention of encoding array fields (e.g.
    ``clobTokenIds``) as JSON strings.
    """
    slug = event.get("slug", "")
    if BTC_5M_SLUG_FRAGMENT not in slug:
        return None

    # Timestamps
    end_date_iso = event.get("endDate", "")
    end_ts = _parse_iso_to_ts(end_date_iso) if end_date_iso else 0.0
    start_date_iso = event.get("startDate", "")
    start_ts = _parse_iso_to_ts(start_date_iso) if start_date_iso else 0.0

    if end_ts == 0.0 or now > end_ts:
        return None  # expired or unparseable

    market_id = event.get("conditionId", event.get("id", slug))
    markets: list = event.get("markets", [])

    token_id_up: Optional[str] = None
    token_id_down: Optional[str] = None

    for mkt in markets:
        # clobTokenIds may be a JSON string or a list
        raw_tids = mkt.get("clobTokenIds") or mkt.get("clob_token_ids") or []
        token_ids = _decode_json_field(raw_tids)

        if len(token_ids) == 2:
            # Determine which token is UP and which is DOWN from outcomes
            raw_outcomes = mkt.get("outcomes") or []
            outcomes = _decode_json_field(raw_outcomes)
            if outcomes and len(outcomes) == 2:
                up_idx = 0  # default: first token = UP/Yes
                for i, o in enumerate(outcomes):
                    if str(o).upper() in ("NO", "DOWN"):
                        up_idx = 1 - i  # the OTHER one is UP
                        break
                token_id_up = str(token_ids[up_idx])
                token_id_down = str(token_ids[1 - up_idx])
            else:
                # No outcome labels – assume index 0 = UP, 1 = DOWN
                token_id_up = str(token_ids[0])
                token_id_down = str(token_ids[1])
            break  # found token IDs in this market entry

        # Single-outcome market entry: identify by outcome label
        raw_outcome_label = mkt.get("outcome", "")
        outcome_label = str(raw_outcome_label).upper()
        token_id = str(mkt.get("conditionId", mkt.get("id", "")))
        if not token_id:
            continue
        if "UP" in outcome_label or "YES" in outcome_label:
            token_id_up = token_id
        elif "DOWN" in outcome_label or "NO" in outcome_label:
            token_id_down = token_id

    if not token_id_up or not token_id_down:
        logger.debug(
            "Could not extract UP/DOWN token IDs from event %s (markets=%d)",
            slug,
            len(markets),
        )
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


def _parse_standalone_market(mkt: dict, now: float) -> Optional[MarketInfo]:
    """Build a :class:`~polymarket.models.MarketInfo` from a bare /markets entry.

    A standalone market entry does not group UP/DOWN; both token IDs must be
    present in the ``clobTokenIds`` field.
    """
    question = mkt.get("question", "")
    slug = mkt.get("slug", "")

    if BTC_5M_SLUG_FRAGMENT not in slug and BTC_5M_SLUG_FRAGMENT not in question.lower():
        return None

    end_date_iso = mkt.get("endDate", mkt.get("end_date", ""))
    end_ts = _parse_iso_to_ts(end_date_iso) if end_date_iso else 0.0
    start_date_iso = mkt.get("startDate", mkt.get("start_date", ""))
    start_ts = _parse_iso_to_ts(start_date_iso) if start_date_iso else 0.0

    if end_ts == 0.0 or now > end_ts:
        return None

    raw_tids = mkt.get("clobTokenIds") or mkt.get("clob_token_ids") or []
    token_ids = _decode_json_field(raw_tids)
    if len(token_ids) != 2:
        return None

    # Determine UP/DOWN ordering from outcomes if available
    raw_outcomes = mkt.get("outcomes") or []
    outcomes = _decode_json_field(raw_outcomes)
    if outcomes and len(outcomes) == 2:
        up_idx = 0
        for i, o in enumerate(outcomes):
            if str(o).upper() in ("NO", "DOWN"):
                up_idx = 1 - i
                break
        token_id_up = str(token_ids[up_idx])
        token_id_down = str(token_ids[1 - up_idx])
    else:
        token_id_up = str(token_ids[0])
        token_id_down = str(token_ids[1])

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
