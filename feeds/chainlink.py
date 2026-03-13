"""Chainlink BTC/USD price feed.

Chainlink is the resolution oracle used by Polymarket for BTC Up/Down 5m
markets.  This feed periodically reads the latest answer from the
AggregatorV3Interface contract on Polygon.

Requirements:
  - WEB3_POLYGON_RPC: A Polygon RPC URL (e.g. Alchemy / Infura / public)

Falls back to a simple REST approach (Chainlink Data Feeds REST API or a
third-party proxy) if web3 is unavailable.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Optional

import requests

from feeds.base import PriceFeed
from polymarket.endpoints import CHAINLINK_BTC_USD_POLYGON

logger = logging.getLogger(__name__)

# Minimal ABI for the AggregatorV3Interface latestRoundData call
AGGREGATOR_ABI = [
    {
        "inputs": [],
        "name": "latestRoundData",
        "outputs": [
            {"name": "roundId", "type": "uint80"},
            {"name": "answer", "type": "int256"},
            {"name": "startedAt", "type": "uint256"},
            {"name": "updatedAt", "type": "uint256"},
            {"name": "answeredInRound", "type": "uint80"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    },
]

# Alternative: public Chainlink REST proxy (last-resort fallback)
CHAINLINK_PROXY_URL = (
    "https://min-api.cryptocompare.com/data/price?fsym=BTC&tsyms=USD"
)

POLL_INTERVAL = 10  # seconds between Chainlink reads


class ChainlinkFeed(PriceFeed):
    """BTC/USD price from Chainlink on Polygon."""

    def __init__(self) -> None:
        super().__init__()
        self._rpc_url = os.environ.get(
            "WEB3_POLYGON_RPC", "https://polygon-rpc.com"
        )
        self._contract = None
        self._decimals: Optional[int] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._session = requests.Session()

        # Try to initialise web3 contract
        try:
            from web3 import Web3  # type: ignore

            w3 = Web3(Web3.HTTPProvider(self._rpc_url))
            self._contract = w3.eth.contract(
                address=Web3.to_checksum_address(CHAINLINK_BTC_USD_POLYGON),
                abi=AGGREGATOR_ABI,
            )
            self._decimals = self._contract.functions.decimals().call()
            logger.info("Chainlink feed initialised via web3 (decimals=%d)", self._decimals)
        except Exception as exc:
            logger.warning(
                "web3 unavailable or Chainlink contract init failed: %s – "
                "falling back to REST proxy",
                exc,
            )

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="chainlink-feed"
        )
        self._thread.start()
        logger.info("Chainlink feed started")

    def stop(self) -> None:
        self._running = False

    def _run(self) -> None:
        while self._running:
            price = self._fetch()
            if price is not None:
                self._record(price)
            time.sleep(POLL_INTERVAL)

    def _fetch(self) -> Optional[float]:
        # Try on-chain first
        if self._contract is not None and self._decimals is not None:
            try:
                _, answer, _, updated_at, _ = (
                    self._contract.functions.latestRoundData().call()
                )
                price = answer / (10**self._decimals)
                return price
            except Exception as exc:
                logger.debug("Chainlink on-chain read failed: %s", exc)

        # Fallback to REST proxy
        try:
            resp = self._session.get(CHAINLINK_PROXY_URL, timeout=5)
            resp.raise_for_status()
            data = resp.json()
            return float(data.get("USD", 0))
        except Exception as exc:
            logger.warning("Chainlink REST fallback failed: %s", exc)
            return None
