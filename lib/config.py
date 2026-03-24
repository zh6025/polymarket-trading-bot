import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _get_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return float(value)


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return int(value)


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.lower() in ("1", "true", "yes", "on")


@dataclass
class BotConfig:
    private_key: str
    proxy_address: str
    condition_id: str
    yes_token_id: str
    no_token_id: str
    host: str
    chain_id: int
    gamma_host: str
    ws_enabled: bool
    heartbeat_interval: int
    orderbook_poll_seconds: float
    position_poll_seconds: float

    min_order_size: float
    max_position_size: float

    max_daily_loss: float
    max_trades_per_day: int
    cooldown_seconds: int

    imbalance_threshold: float
    min_spread: float
    profit_take_pct: float
    stop_loss_pct: float

    dry_run: bool
    trading_enabled: bool

    db_path: str
    state_file_path: str
    log_level: str

    hard_stop_new_entry_sec: int
    min_secs_main_entry: int
    min_secs_hedge_entry: int

    max_main_price: float
    max_hedge_price: float
    min_main_price: float
    min_hedge_price: float

    max_main_spread: float
    max_hedge_spread: float

    min_main_depth_usdc: float
    min_hedge_depth_usdc: float

    min_win_prob: float
    max_hedge_ratio: float
    min_meaningful_hedge_ratio: float

    one_position_per_market: bool
    consecutive_loss_limit: int
    daily_loss_limit_usdc: float
    daily_trade_limit: int


def load_config() -> BotConfig:
    return BotConfig(
        private_key=os.getenv("PK", ""),
        proxy_address=os.getenv("PROXY_ADDRESS", ""),
        condition_id=os.getenv("MARKET_CONDITION_ID", ""),
        yes_token_id=os.getenv("YES_TOKEN_ID", ""),
        no_token_id=os.getenv("NO_TOKEN_ID", ""),
        host=os.getenv("POLYMARKET_HOST", "https://clob.polymarket.com"),
        chain_id=_get_int("CHAIN_ID", 137),
        gamma_host=os.getenv("GAMMA_HOST", "https://gamma-api.polymarket.com"),
        ws_enabled=_get_bool("WS_ENABLED", False),
        heartbeat_interval=_get_int("HEARTBEAT_INTERVAL", 15),
        orderbook_poll_seconds=_get_float("ORDERBOOK_POLL_SECONDS", 2.0),
        position_poll_seconds=_get_float("POSITION_POLL_SECONDS", 5.0),

        min_order_size=_get_float("MIN_ORDER_SIZE", 5.0),
        max_position_size=_get_float("MAX_POSITION_SIZE", 50.0),

        max_daily_loss=_get_float("MAX_DAILY_LOSS", 30.0),
        max_trades_per_day=_get_int("MAX_TRADES_PER_DAY", 20),
        cooldown_seconds=_get_int("COOLDOWN_SECONDS", 30),

        imbalance_threshold=_get_float("IMBALANCE_THRESHOLD", 1.8),
        min_spread=_get_float("MIN_SPREAD", 0.01),
        profit_take_pct=_get_float("PROFIT_TAKE_PCT", 0.03),
        stop_loss_pct=_get_float("STOP_LOSS_PCT", 0.02),

        dry_run=_get_bool("DRY_RUN", True),
        trading_enabled=_get_bool("TRADING_ENABLED", False),

        db_path=os.getenv("DB_PATH", "bot_data.db"),
        state_file_path=os.getenv("STATE_FILE_PATH", "bot_state.json"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),

        hard_stop_new_entry_sec=_get_int("HARD_STOP_NEW_ENTRY_SEC", 30),
        min_secs_main_entry=_get_int("MIN_SECS_MAIN_ENTRY", 90),
        min_secs_hedge_entry=_get_int("MIN_SECS_HEDGE_ENTRY", 60),

        max_main_price=_get_float("MAX_MAIN_PRICE", 0.66),
        max_hedge_price=_get_float("MAX_HEDGE_PRICE", 0.25),
        min_main_price=_get_float("MIN_MAIN_PRICE", 0.20),
        min_hedge_price=_get_float("MIN_HEDGE_PRICE", 0.03),

        max_main_spread=_get_float("MAX_MAIN_SPREAD", 0.03),
        max_hedge_spread=_get_float("MAX_HEDGE_SPREAD", 0.02),

        min_main_depth_usdc=_get_float("MIN_MAIN_DEPTH_USDC", 10.0),
        min_hedge_depth_usdc=_get_float("MIN_HEDGE_DEPTH_USDC", 5.0),

        min_win_prob=_get_float("MIN_WIN_PROB", 0.55),
        max_hedge_ratio=_get_float("MAX_HEDGE_RATIO", 0.33),
        min_meaningful_hedge_ratio=_get_float("MIN_MEANINGFUL_HEDGE_RATIO", 0.05),

        one_position_per_market=_get_bool("ONE_POSITION_PER_MARKET", True),
        consecutive_loss_limit=_get_int("CONSECUTIVE_LOSS_LIMIT", 3),
        daily_loss_limit_usdc=_get_float("DAILY_LOSS_LIMIT_USDC", 20.0),
        daily_trade_limit=_get_int("DAILY_TRADE_LIMIT", 20),
    )
