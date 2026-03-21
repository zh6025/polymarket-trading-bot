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

        # 策略选择 / Strategy selection
        # Supported values: 'grid' | 'directional' | 'momentum_hedge'
        self.strategy = self.get_env_variable('STRATEGY', required=False, default='grid')

        # 动量对冲策略参数 / Momentum hedge strategy parameters
        self.trigger_threshold = float(self.get_env_variable('TRIGGER_THRESHOLD', required=False, default='0.70'))
        self.total_bet_size = float(self.get_env_variable('TOTAL_BET_SIZE', required=False, default='4.0'))
        self.min_remaining_seconds = float(self.get_env_variable('MIN_REMAINING_SECONDS', required=False, default='60'))
        self.max_trigger_price = float(self.get_env_variable('MAX_TRIGGER_PRICE', required=False, default='0.85'))
        self.use_dynamic_ratio = self.get_env_variable('USE_DYNAMIC_RATIO', required=False, default='true').lower() != 'false'
        self.fixed_hedge_ratio = float(self.get_env_variable('FIXED_HEDGE_RATIO', required=False, default='0.33'))
        self.win_rate_slope = float(self.get_env_variable('WIN_RATE_SLOPE', required=False, default='1.0'))

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
            'strategy': self.strategy,
            'trigger_threshold': self.trigger_threshold,
            'total_bet_size': self.total_bet_size,
            'min_remaining_seconds': self.min_remaining_seconds,
            'max_trigger_price': self.max_trigger_price,
            'use_dynamic_ratio': self.use_dynamic_ratio,
            'fixed_hedge_ratio': self.fixed_hedge_ratio,
            'win_rate_slope': self.win_rate_slope,
        }
