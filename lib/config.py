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
    db_path: str
    log_level: str


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
        db_path=os.getenv("DB_PATH", "bot_data.db"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )
