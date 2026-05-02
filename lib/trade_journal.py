"""Append-only JSONL trade journal.

Every order submission and every settlement is appended as one JSON line so
that ops/compliance/postmortem tooling has a complete, line-buffered record.

Failures while writing the journal are logged but never raise — losing a
journal line is preferable to crashing the live trading loop.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional

from lib.utils import log_warn


def _default_path() -> str:
    return os.environ.get("TRADE_LOG_FILE", "trades.jsonl")


def append(event: str, payload: Dict[str, Any], path: Optional[str] = None) -> None:
    """Append one JSON line tagged with ``event`` and current UTC timestamp.

    Args:
        event: short tag, e.g. ``"submit"`` / ``"settle"`` / ``"cancel"``.
        payload: arbitrary JSON-serialisable dict describing the event.
        path: override file path (mostly for tests). Defaults to env
            ``TRADE_LOG_FILE`` or ``trades.jsonl`` in the working dir.
    """
    target = path or _default_path()
    record = {
        "ts": int(time.time()),
        "event": event,
        **payload,
    }
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True) if os.path.dirname(target) else None
        with open(target, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception as e:  # pragma: no cover - defensive
        log_warn(f"trade journal write failed ({target}): {e}")
