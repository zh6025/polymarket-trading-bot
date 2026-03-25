"""Configuration loader for the Polymarket BTC 5m trading bot."""

import os
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (ValueError, TypeError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (ValueError, TypeError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    val = os.getenv(name, str(default)).strip().lower()
    return val in ("1", "true", "yes")


class Config:
    """All configuration values read from environment variables."""

    def __init__(self):
        # ── Runtime ──────────────────────────────────────────
        self.dry_run = _env_bool("DRY_RUN", True)
        self.trading_enabled = _env_bool("TRADING_ENABLED", True)
        self.state_file_path = _env("STATE_FILE_PATH", "bot_state.json")
        self.log_level = _env("LOG_LEVEL", "INFO").upper()
        self.db_path = _env("DB_PATH", "bot_data.db")

        # ── Polymarket API / Auth ────────────────────────────
        self.host = _env("CLOB_HOST", "https://clob.polymarket.com")
        self.chain_id = _env_int("CHAIN_ID", 137)
        self.private_key = _env("PRIVATE_KEY", "")
        self.proxy_address = _env("PROXY_ADDRESS", "")
        self.api_key = _env("API_KEY", "demo-key")

        # ── Legacy grid strategy (still read by old code) ───
        self.series_slug = _env("SERIES_SLUG", "btc-updown-5m")
        self.levels_each_side = _env_int("LEVELS_EACH_SIDE", 5)
        self.grid_step = _env_float("GRID_STEP", 0.02)
        self.order_size = _env_float("ORDER_SIZE", 5.0)
        self.trade_both_outcomes = _env_bool("TRADE_BOTH_OUTCOMES", True)

        # ── Order sizing ─────────────────────────────────────
        self.min_order_size = _env_float("MIN_ORDER_SIZE", 5.0)
        self.max_position_size = _env_float("MAX_POSITION_SIZE", 500.0)

        # ── Risk management ──────────────────────────────────
        self.max_daily_loss = _env_float("MAX_DAILY_LOSS", 100.0)
        self.max_trades_per_day = _env_int("MAX_TRADES_PER_DAY", 50)
        self.cooldown_seconds = _env_int("COOLDOWN_SECONDS", 30)
        self.consecutive_loss_limit = _env_int("CONSECUTIVE_LOSS_LIMIT", 5)
        self.daily_loss_limit_usdc = _env_float("DAILY_LOSS_LIMIT_USDC", 100.0)
        self.daily_trade_limit = _env_int("DAILY_TRADE_LIMIT", 50)

        # ── Legacy alias ─────────────────────────────────────
        self.daily_loss_limit = self.max_daily_loss

        # ── Market poll ──────────────────────────────────────
        self.polling_interval = _env_int("POLLING_INTERVAL", 5000)
        self.orderbook_poll_seconds = _env_int("ORDERBOOK_POLL_SECONDS", 5)

        # ── Strategy tuning ──────────────────────────────────
        self.profit_take_pct = _env_float("PROFIT_TAKE_PCT", 0.15)
        self.stop_loss_pct = _env_float("STOP_LOSS_PCT", 0.10)
        self.imbalance_threshold = _env_float("IMBALANCE_THRESHOLD", 0.65)
        self.min_spread = _env_float("MIN_SPREAD", 0.02)

        # Entry timing / filtering
        self.hard_stop_new_entry_sec = _env_int("HARD_STOP_NEW_ENTRY_SEC", 60)
        self.min_secs_main_entry = _env_int("MIN_SECS_MAIN_ENTRY", 10)
        self.min_secs_hedge_entry = _env_int("MIN_SECS_HEDGE_ENTRY", 10)

        # Price range for main leg
        self.min_main_price = _env_float("MIN_MAIN_PRICE", 0.55)
        self.max_main_price = _env_float("MAX_MAIN_PRICE", 0.80)

        # Price range for hedge leg
        self.min_hedge_price = _env_float("MIN_HEDGE_PRICE", 0.15)
        self.max_hedge_price = _env_float("MAX_HEDGE_PRICE", 0.45)

        # Spread / depth guards
        self.max_main_spread = _env_float("MAX_MAIN_SPREAD", 0.05)
        self.max_hedge_spread = _env_float("MAX_HEDGE_SPREAD", 0.08)
        self.min_main_depth_usdc = _env_float("MIN_MAIN_DEPTH_USDC", 50.0)
        self.min_hedge_depth_usdc = _env_float("MIN_HEDGE_DEPTH_USDC", 20.0)

        # Kelly / sizing
        self.min_win_prob = _env_float("MIN_WIN_PROB", 0.55)
        self.max_hedge_ratio = _env_float("MAX_HEDGE_RATIO", 0.70)
        self.min_meaningful_hedge_ratio = _env_float("MIN_MEANINGFUL_HEDGE_RATIO", 0.05)

        # Position limits
        self.one_position_per_market = _env_bool("ONE_POSITION_PER_MARKET", True)

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def load_config() -> Config:
    """Return a fully-loaded Config instance."""
    cfg = Config()
    logger.info(
        f"Config: dry_run={cfg.dry_run} trading_enabled={cfg.trading_enabled} "
        f"min_order_size={cfg.min_order_size} max_daily_loss={cfg.max_daily_loss}"
    )
    return cfg

