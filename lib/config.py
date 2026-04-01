"""
Config: Configuration for the BTC 5m multi-window trading bot.
All settings loaded from environment variables with safe defaults.
"""
import os
from dotenv import load_dotenv

load_dotenv()


def _bool(key: str, default: bool) -> bool:
    val = os.getenv(key, "").strip().lower()
    if val in ('true', '1', 'yes'):
        return True
    if val in ('false', '0', 'no'):
        return False
    return default


def _float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


def _int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


class Config:
    # ── Safety ──────────────────────────────────────────────────────────────
    TRADING_ENABLED: bool = _bool('TRADING_ENABLED', False)
    DRY_RUN: bool = _bool('DRY_RUN', True)

    # ── Polymarket API ───────────────────────────────────────────────────────
    API_KEY: str = os.getenv('API_KEY', '')
    API_SECRET: str = os.getenv('API_SECRET', '')
    API_PASSPHRASE: str = os.getenv('API_PASSPHRASE', '')

    # ── Strategy: Window feature flags ──────────────────────────────────────
    # Window 0 is disabled by default (early momentum, experimental)
    WINDOW0_ENABLED: bool = _bool('WINDOW0_ENABLED', False)

    # ── Strategy: Price thresholds ───────────────────────────────────────────
    # Hard cap: never buy if market price is above this
    HARD_CAP_PRICE: float = _float('HARD_CAP_PRICE', 0.85)
    # Minimum price (confidence) to enter in window 0 (stricter)
    MIN_CONFIDENCE_W0: float = _float('MIN_CONFIDENCE_W0', 0.70)
    # Minimum price (confidence) to enter in window 1
    MIN_CONFIDENCE_W1: float = _float('MIN_CONFIDENCE_W1', 0.55)
    # Minimum price for late entry (window 2 only)
    LATE_ENTRY_MIN_PRICE: float = _float('LATE_ENTRY_MIN_PRICE', 0.65)

    # ── Strategy: Market quality filters ────────────────────────────────────
    MAX_SPREAD: float = _float('MAX_SPREAD', 0.05)
    MIN_DEPTH: float = _float('MIN_DEPTH', 50.0)

    # ── Strategy: Bias computation ───────────────────────────────────────────
    MOMENTUM_5M_THRESHOLD: float = _float('MOMENTUM_5M_THRESHOLD', 0.0015)
    MOMENTUM_15M_THRESHOLD: float = _float('MOMENTUM_15M_THRESHOLD', 0.003)

    # ── Strategy: Volatility safety ──────────────────────────────────────────
    # If recent 10s price change exceeds this fraction, skip (too volatile)
    MAX_RECENT_VOLATILITY: float = _float('MAX_RECENT_VOLATILITY', 0.20)

    # ── Bet sizing ───────────────────────────────────────────────────────────
    BET_SIZE_USDC: float = _float('BET_SIZE_USDC', 3.0)

    # ── Risk controls ────────────────────────────────────────────────────────
    DAILY_LOSS_LIMIT_USDC: float = _float('DAILY_LOSS_LIMIT_USDC', 20.0)
    DAILY_TRADE_LIMIT: int = _int('DAILY_TRADE_LIMIT', 20)
    CONSECUTIVE_LOSS_LIMIT: int = _int('CONSECUTIVE_LOSS_LIMIT', 3)

    # ── Polling ──────────────────────────────────────────────────────────────
    POLLING_INTERVAL: int = _int('POLLING_INTERVAL', 5000)  # milliseconds

    # ── Logging ──────────────────────────────────────────────────────────────
    LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO')
