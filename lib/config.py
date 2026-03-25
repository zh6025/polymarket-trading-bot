import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    def __init__(self):
        # --- Core ---
        self.api_key = self.get_env_variable('API_KEY', default='demo-key')
        self.series_slug = self.get_env_variable('SERIES_SLUG', default='btc-up-or-down-5m')
        self.dry_run = self.get_env_variable('DRY_RUN', default='true').lower() == 'true'
        self.polling_interval = int(self.get_env_variable('POLLING_INTERVAL', default='60000'))
        self.trading_enabled = self.get_env_variable('TRADING_ENABLED', default='false').lower() == 'true'

        # --- Legacy grid params (kept for backward compat) ---
        self.levels_each_side = int(self.get_env_variable('LEVELS_EACH_SIDE', default='5'))
        self.grid_step = float(self.get_env_variable('GRID_STEP', default='0.02'))
        self.order_size = float(self.get_env_variable('ORDER_SIZE', default='5'))
        self.trade_both_outcomes = self.get_env_variable('TRADE_BOTH_OUTCOMES', default='true').lower() == 'true'

        # --- Risk controls ---
        self.daily_loss_limit = float(self.get_env_variable('DAILY_LOSS_LIMIT_USDC', default='20'))
        self.daily_trade_limit = int(self.get_env_variable('DAILY_TRADE_LIMIT', default='20'))
        self.consecutive_loss_limit = int(self.get_env_variable('CONSECUTIVE_LOSS_LIMIT', default='3'))
        self.max_position_size = float(self.get_env_variable('MAX_POSITION_SIZE', default='5000'))
        self.hard_stop_new_entry_sec = int(self.get_env_variable('HARD_STOP_NEW_ENTRY_SEC', default='30'))
        self.min_secs_main_entry = int(self.get_env_variable('MIN_SECS_MAIN_ENTRY', default='90'))
        self.min_secs_hedge_entry = int(self.get_env_variable('MIN_SECS_HEDGE_ENTRY', default='60'))

        # --- Strategy selection ---
        self.strategy = self.get_env_variable('STRATEGY', default='imbalance')

        # --- Directional strategy (EMA+ATR) ---
        self.ema_fast_period = int(self.get_env_variable('EMA_FAST_PERIOD', default='3'))
        self.ema_slow_period = int(self.get_env_variable('EMA_SLOW_PERIOD', default='8'))
        self.atr_period = int(self.get_env_variable('ATR_PERIOD', default='10'))
        self.atr_threshold_pct = float(self.get_env_variable('ATR_THRESHOLD_PCT', default='0.0003'))
        self.max_entry_price = float(self.get_env_variable('MAX_ENTRY_PRICE', default='0.55'))
        self.bet_size = float(self.get_env_variable('BET_SIZE', default='5'))
        self.ema_signal_buffer = float(self.get_env_variable('EMA_SIGNAL_BUFFER', default='0.0002'))

        # --- Momentum hedge strategy ---
        self.trigger_threshold = float(self.get_env_variable('TRIGGER_THRESHOLD', default='0.70'))
        self.total_bet_size = float(self.get_env_variable('TOTAL_BET_SIZE', default='4.0'))
        self.max_trigger_price = float(self.get_env_variable('MAX_TRIGGER_PRICE', default='0.85'))
        self.use_dynamic_ratio = self.get_env_variable('USE_DYNAMIC_RATIO', default='true').lower() == 'true'
        self.fixed_hedge_ratio = float(self.get_env_variable('FIXED_HEDGE_RATIO', default='0.33'))
        self.win_rate_slope = float(self.get_env_variable('WIN_RATE_SLOPE', default='1.0'))

        # --- Imbalance / late-entry strategy ---
        self.market_entry_window = int(self.get_env_variable('MARKET_ENTRY_WINDOW', default='120'))
        self.entry_delay_seconds = int(self.get_env_variable('ENTRY_DELAY_SECONDS', default='90'))
        self.trade_window_end_seconds = int(self.get_env_variable('TRADE_WINDOW_END_SECONDS', default='270'))
        self.dominance_threshold = float(self.get_env_variable('DOMINANCE_THRESHOLD', default='0.68'))
        self.max_spread_pct = float(self.get_env_variable('MAX_SPREAD_PCT', default='0.05'))
        self.min_samples = int(self.get_env_variable('MIN_SAMPLES', default='5'))
        self.confirmation_checks = int(self.get_env_variable('CONFIRMATION_CHECKS', default='2'))

        # --- Main/hedge bet sizing ---
        self.main_notional = float(self.get_env_variable('MAIN_NOTIONAL', default='5.0'))
        self.main_bet_size_usdc = float(self.get_env_variable('MAIN_BET_SIZE_USDC', default='3.0'))
        self.main_max_price = float(self.get_env_variable('MAIN_MAX_PRICE', default='0.66'))
        self.enable_hedge = self.get_env_variable('ENABLE_HEDGE', default='false').lower() == 'true'
        self.hedge_notional = float(self.get_env_variable('HEDGE_NOTIONAL', default='1.0'))
        self.hedge_max_price = float(self.get_env_variable('HEDGE_MAX_PRICE', default='0.15'))
        self.hedge_max_price_decision = float(self.get_env_variable('HEDGE_MAX_PRICE_DECISION', default='0.25'))

        # --- Logging ---
        self.log_level = self.get_env_variable('LOG_LEVEL', default='info')

    def get_env_variable(self, var_name, required=False, default=None):
        value = os.getenv(var_name)
        if value is None:
            if required:
                raise ValueError(f'Environment variable {var_name} is required.')
            return default
        return value

    def to_dict(self):
        return {
            'strategy': self.strategy,
            'series_slug': self.series_slug,
            'dry_run': self.dry_run,
            'trading_enabled': self.trading_enabled,
            'main_max_price': self.main_max_price,
            'trigger_threshold': self.trigger_threshold,
            'daily_loss_limit': self.daily_loss_limit,
            'daily_trade_limit': self.daily_trade_limit,
            'consecutive_loss_limit': self.consecutive_loss_limit,
        }
