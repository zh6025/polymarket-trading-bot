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

        # 方向性策略参数 / Directional strategy parameters
        # 策略选择: 'directional'（推荐）或 'grid'（旧版兼容）
        self.strategy = self.get_env_variable('STRATEGY', required=False, default='directional')
        # EMA 快线周期 / Fast EMA period
        self.ema_fast_period = int(self.get_env_variable('EMA_FAST_PERIOD', required=False, default='3'))
        # EMA 慢线周期 / Slow EMA period
        self.ema_slow_period = int(self.get_env_variable('EMA_SLOW_PERIOD', required=False, default='8'))
        # ATR 计算周期 / ATR calculation period
        self.atr_period = int(self.get_env_variable('ATR_PERIOD', required=False, default='10'))
        # ATR 阈值比例（低于此值跳过）/ ATR threshold as fraction of price
        self.atr_threshold_pct = float(self.get_env_variable('ATR_THRESHOLD_PCT', required=False, default='0.0003'))
        # 最大入场价格（ask 超过此值不买）/ Max ask price to enter a position
        self.max_entry_price = float(self.get_env_variable('MAX_ENTRY_PRICE', required=False, default='0.55'))
        # 每笔下注金额（USDC）/ Bet size per trade (USDC)
        self.bet_size = float(self.get_env_variable('BET_SIZE', required=False, default='5'))
        # 市场入场时间窗口（秒，从市场开放起算）/ Entry window in seconds from market open
        self.market_entry_window = int(self.get_env_variable('MARKET_ENTRY_WINDOW', required=False, default='120'))
        # EMA 信号缓冲区（防止信号频繁反转）/ Buffer to avoid EMA signal flip-flop
        self.ema_signal_buffer = float(self.get_env_variable('EMA_SIGNAL_BUFFER', required=False, default='0.0002'))

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
            # 方向性策略参数 / Directional strategy parameters
            'strategy': self.strategy,
            'ema_fast_period': self.ema_fast_period,
            'ema_slow_period': self.ema_slow_period,
            'atr_period': self.atr_period,
            'atr_threshold_pct': self.atr_threshold_pct,
            'max_entry_price': self.max_entry_price,
            'bet_size': self.bet_size,
            'market_entry_window': self.market_entry_window,
            'ema_signal_buffer': self.ema_signal_buffer,
        }
