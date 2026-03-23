import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    def __init__(self):
        self.api_key = self.get_env_variable('API_KEY', required=False, default='demo-key')
        self.series_slug = self.get_env_variable('SERIES_SLUG', required=False, default='btc-up-or-down-5m')
        self.levels_each_side = int(self.get_env_variable('LEVELS_EACH_SIDE', required=False, default='5'))
        self.grid_step = float(self.get_env_variable('GRID_STEP', required=False, default='0.02'))
        self.order_size = float(self.get_env_variable('ORDER_SIZE', required=False, default='5'))
        self.trade_both_outcomes = self.get_env_variable('TRADE_BOTH_OUTCOMES', required=False, default='true').lower() == 'true'
        self.daily_loss_limit = float(self.get_env_variable('DAILY_LOSS_LIMIT', required=False, default='1000'))
        self.max_position_size = float(self.get_env_variable('MAX_POSITION_SIZE', required=False, default='5000'))
        self.dry_run = self.get_env_variable('DRY_RUN', required=False, default='true').lower() == 'true'
        self.polling_interval = int(self.get_env_variable('POLLING_INTERVAL', required=False, default='60000'))

        # ----------------------------------------------------------------
        # Production risk-control parameters
        # ----------------------------------------------------------------

        # Global controls
        self.trading_enabled = self.get_env_variable(
            'TRADING_ENABLED', required=False, default='false').lower() == 'true'
        self.one_position_per_market = self.get_env_variable(
            'ONE_POSITION_PER_MARKET', required=False, default='true').lower() == 'true'
        self.daily_trade_limit = int(self.get_env_variable(
            'DAILY_TRADE_LIMIT', required=False, default='20'))
        self.consecutive_loss_limit = int(self.get_env_variable(
            'CONSECUTIVE_LOSS_LIMIT', required=False, default='3'))
        self.daily_loss_limit_usdc = float(self.get_env_variable(
            'DAILY_LOSS_LIMIT_USDC', required=False, default='20'))
        self.cooldown_after_trade_sec = int(self.get_env_variable(
            'COOLDOWN_AFTER_TRADE_SEC', required=False, default='300'))
        self.state_file = self.get_env_variable(
            'STATE_FILE', required=False, default='bot_state.json')

        # Time filters
        self.hard_stop_new_entry_sec = float(self.get_env_variable(
            'HARD_STOP_NEW_ENTRY_SEC', required=False, default='30'))
        self.min_secs_main_entry = float(self.get_env_variable(
            'MIN_SECS_MAIN_ENTRY', required=False, default='90'))
        self.min_secs_hedge_entry = float(self.get_env_variable(
            'MIN_SECS_HEDGE_ENTRY', required=False, default='60'))

        # Main leg price limits
        self.main_bet_size_usdc = float(self.get_env_variable(
            'MAIN_BET_SIZE_USDC', required=False, default='3.0'))
        self.main_max_price = float(self.get_env_variable(
            'MAIN_MAX_PRICE', required=False, default='0.66'))
        self.main_min_price = float(self.get_env_variable(
            'MAIN_MIN_PRICE', required=False, default='0.20'))
        self.main_max_spread = float(self.get_env_variable(
            'MAIN_MAX_SPREAD', required=False, default='0.03'))
        self.main_min_depth = float(self.get_env_variable(
            'MAIN_MIN_DEPTH', required=False, default='10.0'))

        # Hedge leg price limits
        self.enable_hedge = self.get_env_variable(
            'ENABLE_HEDGE', required=False, default='true').lower() == 'true'
        self.hedge_max_price = float(self.get_env_variable(
            'HEDGE_MAX_PRICE', required=False, default='0.25'))
        self.hedge_min_price = float(self.get_env_variable(
            'HEDGE_MIN_PRICE', required=False, default='0.03'))
        self.hedge_max_spread = float(self.get_env_variable(
            'HEDGE_MAX_SPREAD', required=False, default='0.02'))
        self.hedge_min_depth = float(self.get_env_variable(
            'HEDGE_MIN_DEPTH', required=False, default='5.0'))

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
            'levels_each_side': self.levels_each_side,
            'grid_step': self.grid_step,
            'order_size': self.order_size,
            'trade_both_outcomes': self.trade_both_outcomes,
            'dry_run': self.dry_run,
            'trading_enabled': self.trading_enabled,
            'one_position_per_market': self.one_position_per_market,
            'daily_trade_limit': self.daily_trade_limit,
            'consecutive_loss_limit': self.consecutive_loss_limit,
            'daily_loss_limit_usdc': self.daily_loss_limit_usdc,
            'cooldown_after_trade_sec': self.cooldown_after_trade_sec,
            'hard_stop_new_entry_sec': self.hard_stop_new_entry_sec,
            'min_secs_main_entry': self.min_secs_main_entry,
            'min_secs_hedge_entry': self.min_secs_hedge_entry,
            'main_bet_size_usdc': self.main_bet_size_usdc,
            'main_max_price': self.main_max_price,
            'main_min_price': self.main_min_price,
            'main_max_spread': self.main_max_spread,
            'main_min_depth': self.main_min_depth,
            'enable_hedge': self.enable_hedge,
            'hedge_max_price': self.hedge_max_price,
            'hedge_min_price': self.hedge_min_price,
            'hedge_max_spread': self.hedge_max_spread,
            'hedge_min_depth': self.hedge_min_depth,
        }
