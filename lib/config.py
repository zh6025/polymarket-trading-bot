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
    # TRADING_ENABLED=true  → 允许交易 (allow trading)
    # TRADING_ENABLED=false → 观察模式，不下单 (observation only, no orders)
    TRADING_ENABLED: bool = _bool('TRADING_ENABLED', False)
    # DRY_RUN=true  → 模拟交易，不发真实订单 (simulated, no real orders)
    # DRY_RUN=false → 真实交易，发真实订单 (real trading, real orders)
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

    # ── Legacy market-making: minimum profitable spread ──────────────────
    # 做市商最低盈利价差 (absolute floor, must exceed fees)
    # With 1% fee per side: round-trip fee on $1.00 = $0.02, so min spread must be > 0.02
    MIN_PROFIT_SPREAD: float = _float('MIN_PROFIT_SPREAD', 0.02)
    # 做市商手续费率 (per side, default 1%)
    FEE_RATE: float = _float('FEE_RATE', 0.01)

    # ── Strategy: Bias computation ───────────────────────────────────────────
    MOMENTUM_5M_THRESHOLD: float = _float('MOMENTUM_5M_THRESHOLD', 0.0015)
    MOMENTUM_15M_THRESHOLD: float = _float('MOMENTUM_15M_THRESHOLD', 0.003)

    # ── Strategy: Volatility safety ──────────────────────────────────────────
    # If recent 10s price change exceeds this fraction, skip (too volatile)
    MAX_RECENT_VOLATILITY: float = _float('MAX_RECENT_VOLATILITY', 0.20)
    # Maximum age of BTC data before it is considered stale (seconds)
    BTC_DATA_MAX_AGE_SEC: float = _float('BTC_DATA_MAX_AGE_SEC', 30.0)

    # ── Bet sizing (per-window) ───────────────────────────────────────────
    # 每个窗口独立下注金额 (USDC)
    BET_SIZE_W0: float = _float('BET_SIZE_W0', 3.0)   # Window 0: 早期动量
    BET_SIZE_W1: float = _float('BET_SIZE_W1', 5.0)   # Window 1: 主入场
    BET_SIZE_W2: float = _float('BET_SIZE_W2', 3.0)   # Window 2: 晚期入场

    # ── Risk controls ────────────────────────────────────────────────────────
    DAILY_LOSS_LIMIT_USDC: float = _float('DAILY_LOSS_LIMIT_USDC', 20.0)
    DAILY_TRADE_LIMIT: int = _int('DAILY_TRADE_LIMIT', 20)
    CONSECUTIVE_LOSS_LIMIT: int = _int('CONSECUTIVE_LOSS_LIMIT', 3)

    # ── Polling ──────────────────────────────────────────────────────────────
    POLLING_INTERVAL: int = min(_int('POLLING_INTERVAL', 5000), 5000)  # ms, max 5000

    # ── Auto-redeem ─────────────────────────────────────────────────────────
    # 自动赎回已结算仓位，回收USDC (auto-redeem resolved positions)
    AUTO_REDEEM: bool = _bool('AUTO_REDEEM', True)

    # ── Logging ──────────────────────────────────────────────────────────────
    LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO')
