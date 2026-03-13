"""Polymarket CLOB authentication helpers.

Polymarket's CLOB API supports two authentication tiers:
  - L1 Auth: Signs a message with the user's Ethereum private key to derive
    CLOB API credentials (key + secret + passphrase).
  - L2 Auth: Signs individual orders with the Ethereum private key using
    EIP-712.

This module provides a thin wrapper that builds the headers required for
authenticated CLOB requests.  Actual order signing is delegated to
py-clob-client which handles EIP-712 internally.
"""
from __future__ import annotations

import os
from typing import Optional


def get_api_credentials(require_pk: bool = True) -> dict[str, str]:
    """Return CLOB API credentials from environment variables.

    Required environment variables (for live trading):
      PK              – Ethereum private key (hex, with or without 0x prefix)
      POLYMARKET_API_KEY       – CLOB API key
      POLYMARKET_API_SECRET    – CLOB API secret
      POLYMARKET_API_PASSPHRASE– CLOB API passphrase

    Args:
        require_pk: When False, a missing PK only logs a warning instead of
            raising an error.  Set to False for DRY_RUN / read-only usage
            where order placement is not needed.
    """
    import logging as _logging
    _log = _logging.getLogger(__name__)

    pk = os.environ.get("PK", "")
    api_key = os.environ.get("POLYMARKET_API_KEY", "")
    api_secret = os.environ.get("POLYMARKET_API_SECRET", "")
    api_passphrase = os.environ.get("POLYMARKET_API_PASSPHRASE", "")

    if not pk:
        msg = (
            "PK (Ethereum private key) is not set. "
            "Order placement will be unavailable. "
            "Set PK in your .env file to enable live trading."
        )
        if require_pk:
            raise EnvironmentError(msg)
        _log.warning(msg)

    return {
        "pk": pk,
        "api_key": api_key,
        "api_secret": api_secret,
        "api_passphrase": api_passphrase,
    }


def get_chain_id() -> int:
    """Return the chain ID for Polygon (137) or override via env."""
    return int(os.environ.get("CHAIN_ID", "137"))


def get_clob_host() -> str:
    """Return the CLOB base URL (can be overridden for testing)."""
    from polymarket.endpoints import CLOB_BASE_URL  # local import avoids cycles

    return os.environ.get("CLOB_BASE_URL", CLOB_BASE_URL)
