import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    def __init__(self):
        self.api_key = self.get_env_variable('API_KEY', required=False, default='demo-key')
        self.series_slug = self.get_env_variable('SERIES_SLUG', required=False, default='btc-up-or-down-5m')
        self.daily_loss_limit = float(self.get_env_variable('DAILY_LOSS_LIMIT', required=False, default='100'))
        self.max_position_size = float(self.get_env_variable('MAX_POSITION_SIZE', required=False, default='500'))
        self.dry_run = self.get_env_variable('DRY_RUN', required=False, default='true').lower() == 'true'
        self.polling_interval = int(self.get_env_variable('POLLING_INTERVAL', required=False, default='5000'))

        # --- Late-entry imbalance strategy parameters ---
        # Seconds from market open before considering any entry
        self.entry_delay_seconds = int(self.get_env_variable('ENTRY_DELAY_SECONDS', required=False, default='90'))
        # Latest second within the 5-minute window to allow a new entry
        self.trade_window_end_seconds = int(self.get_env_variable('TRADE_WINDOW_END_SECONDS', required=False, default='270'))
        # Implied price threshold for declaring one side dominant (e.g. 0.68 means ≥68 cents)
        self.dominance_threshold = float(self.get_env_variable('DOMINANCE_THRESHOLD', required=False, default='0.68'))
        # Maximum allowed spread percentage before skipping a trade
        self.max_spread_pct = float(self.get_env_variable('MAX_SPREAD_PCT', required=False, default='0.05'))
        # Minimum number of price snapshots required before generating a signal
        self.min_samples = int(self.get_env_variable('MIN_SAMPLES', required=False, default='5'))
        # Consecutive polling cycles the imbalance must persist before entry
        self.confirmation_checks = int(self.get_env_variable('CONFIRMATION_CHECKS', required=False, default='2'))
        # Notional size (USDC) for the primary directional trade
        self.main_notional = float(self.get_env_variable('MAIN_NOTIONAL', required=False, default='5.0'))
        # Enable optional small hedge buy on the weak side
        self.enable_hedge = self.get_env_variable('ENABLE_HEDGE', required=False, default='false').lower() == 'true'
        # Notional size (USDC) for the optional hedge trade
        self.hedge_notional = float(self.get_env_variable('HEDGE_NOTIONAL', required=False, default='1.0'))
        # Maximum price the weak side may have for a hedge to be considered
        self.hedge_max_price = float(self.get_env_variable('HEDGE_MAX_PRICE', required=False, default='0.15'))

    def get_env_variable(self, var_name, required=False, default=None):
        value = os.getenv(var_name)
        if value is None:
            if required:
                raise ValueError(f'Environment variable {var_name} is required.')
            return default
        return value

    def to_dict(self):
        return {
            'series_slug': self.series_slug,
            'dry_run': self.dry_run,
            'entry_delay_seconds': self.entry_delay_seconds,
            'trade_window_end_seconds': self.trade_window_end_seconds,
            'dominance_threshold': self.dominance_threshold,
            'max_spread_pct': self.max_spread_pct,
            'min_samples': self.min_samples,
            'confirmation_checks': self.confirmation_checks,
            'main_notional': self.main_notional,
            'enable_hedge': self.enable_hedge,
            'hedge_notional': self.hedge_notional,
            'hedge_max_price': self.hedge_max_price,
        }
