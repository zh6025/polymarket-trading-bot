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

        # ---- DirectionScorer settings ----
        self.scorer_enabled = self.get_env_variable('SCORER_ENABLED', required=False, default='true').lower() == 'true'
        self.scorer_steepness = float(self.get_env_variable('SCORER_STEEPNESS', required=False, default='3.0'))
        self.scorer_buy_threshold = float(self.get_env_variable('SCORER_BUY_THRESHOLD', required=False, default='0.58'))
        self.scorer_sell_threshold = float(self.get_env_variable('SCORER_SELL_THRESHOLD', required=False, default='0.42'))
        self.min_confidence = float(self.get_env_variable('MIN_CONFIDENCE', required=False, default='0.15'))

        # ---- Price window filters ----
        self.main_price_min = float(self.get_env_variable('MAIN_PRICE_MIN', required=False, default='0.50'))
        self.main_price_max = float(self.get_env_variable('MAIN_PRICE_MAX', required=False, default='0.65'))
        self.hedge_price_min = float(self.get_env_variable('HEDGE_PRICE_MIN', required=False, default='0.05'))
        self.hedge_price_max = float(self.get_env_variable('HEDGE_PRICE_MAX', required=False, default='0.15'))

        # ---- Execution order & fees ----
        self.hedge_first = self.get_env_variable('HEDGE_FIRST', required=False, default='true').lower() == 'true'
        self.fee_rate = float(self.get_env_variable('FEE_RATE', required=False, default='0.02'))

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
            'scorer_enabled': self.scorer_enabled,
            'scorer_steepness': self.scorer_steepness,
            'scorer_buy_threshold': self.scorer_buy_threshold,
            'scorer_sell_threshold': self.scorer_sell_threshold,
            'min_confidence': self.min_confidence,
            'main_price_min': self.main_price_min,
            'main_price_max': self.main_price_max,
            'hedge_price_min': self.hedge_price_min,
            'hedge_price_max': self.hedge_price_max,
            'hedge_first': self.hedge_first,
            'fee_rate': self.fee_rate,
        }
