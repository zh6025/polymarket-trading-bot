import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    def __init__(self):
        # ---- CLOB connection ----
        self.host = self._env("HOST", default="https://clob.polymarket.com")
        self.chain_id = int(self._env("CHAIN_ID", default="137"))
        self.private_key = self._env("PRIVATE_KEY", default="")
        self.proxy_address = self._env("PROXY_ADDRESS", default="")
        self.api_key = self._env("API_KEY", default="")

        # ---- Run mode ----
        self.dry_run = self._env_bool("DRY_RUN", default=True)
        self.trading_enabled = self._env_bool("TRADING_ENABLED", default=False)

        # ---- Market ----
        self.series_slug = self._env("SERIES_SLUG", default="btc-up-or-down-5m")
        self.polling_interval = int(self._env("POLLING_INTERVAL", default="10"))

        # ---- State persistence ----
        self.state_file_path = self._env("STATE_FILE_PATH", default="bot_state.json")

        # ---- Risk controls ----
        self.min_order_size = float(self._env("MIN_ORDER_SIZE", default="3.0"))
        self.max_order_size = float(self._env("MAX_ORDER_SIZE", default="50.0"))
        self.daily_loss_limit_usdc = float(self._env("DAILY_LOSS_LIMIT_USDC", default="20"))
        self.daily_trade_limit = int(self._env("DAILY_TRADE_LIMIT", default="20"))
        self.consecutive_loss_limit = int(self._env("CONSECUTIVE_LOSS_LIMIT", default="3"))

        # ---- Strategy parameters ----
        self.momentum_threshold = float(self._env("MOMENTUM_THRESHOLD", default="0.70"))
        self.edge_factor = float(self._env("EDGE_FACTOR", default="0.05"))
        self.kelly_fraction_cap = float(self._env("KELLY_FRACTION_CAP", default="0.25"))
        self.hedge_ratio = float(self._env("HEDGE_RATIO", default="0.30"))
        self.enable_hedge = self._env_bool("ENABLE_HEDGE", default=True)
        self.bankroll = float(self._env("BANKROLL", default="100.0"))

        # ---- Legacy grid params (kept for backwards compat) ----
        self.levels_each_side = int(self._env("LEVELS_EACH_SIDE", default="5"))
        self.grid_step = float(self._env("GRID_STEP", default="0.02"))
        self.order_size = float(self._env("ORDER_SIZE", default="5"))
        self.trade_both_outcomes = self._env_bool("TRADE_BOTH_OUTCOMES", default=True)
        self.daily_loss_limit = float(self._env("DAILY_LOSS_LIMIT", default="100"))
        self.max_position_size = float(self._env("MAX_POSITION_SIZE", default="500"))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _env(name: str, default: str = "") -> str:
        return os.getenv(name, default)

    @staticmethod
    def _env_bool(name: str, default: bool = False) -> bool:
        raw = os.getenv(name)
        if raw is None:
            return default
        return raw.strip().lower() in ("1", "true", "yes")

    def to_dict(self):
        return {
            "host": self.host,
            "chain_id": self.chain_id,
            "dry_run": self.dry_run,
            "trading_enabled": self.trading_enabled,
            "series_slug": self.series_slug,
            "polling_interval": self.polling_interval,
            "state_file_path": self.state_file_path,
            "min_order_size": self.min_order_size,
            "daily_loss_limit_usdc": self.daily_loss_limit_usdc,
            "daily_trade_limit": self.daily_trade_limit,
            "consecutive_loss_limit": self.consecutive_loss_limit,
            "momentum_threshold": self.momentum_threshold,
            "hedge_ratio": self.hedge_ratio,
            "enable_hedge": self.enable_hedge,
            "bankroll": self.bankroll,
        }
