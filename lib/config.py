import os
from dotenv import load_dotenv

load_dotenv()


def _to_bool(value) -> bool:
    """Tolerant boolean parser.

    Handles the common .env pitfall where a user writes
    `TRADING_ENABLED=true#注释` (no space before the #). python-dotenv reads
    that as the literal string `true#注释`, which a strict `== 'true'` check
    would reject. We split on whitespace and `#` and look at the first token.
    """
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    s = str(value).strip()
    # cut off inline comment
    for sep in ('#',):
        if sep in s:
            s = s.split(sep, 1)[0].strip()
    # take first whitespace-separated token
    s = s.split()[0] if s.split() else ''
    return s.lower() in ('true', '1', 'yes', 'on')


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
        self.dry_run = _to_bool(self.get_env_variable('DRY_RUN', required=False, default='true'))
        self.polling_interval = int(self.get_env_variable('POLLING_INTERVAL', required=False, default='60000'))

        # 策略选择
        self.strategy = self.get_env_variable('STRATEGY', required=False, default='imbalance')

        # 安全开关：必须显式设为 true 才能真实交易
        self.trading_enabled = _to_bool(self.get_env_variable('TRADING_ENABLED', required=False, default='false'))

        # 方向评分器配置
        self.scorer_enabled = self.get_env_variable('SCORER_ENABLED', required=False, default='true').lower() == 'true'
        self.scorer_steepness = float(self.get_env_variable('SCORER_STEEPNESS', required=False, default='3.0'))
        self.scorer_buy_threshold = float(self.get_env_variable('SCORER_BUY_THRESHOLD', required=False, default='0.58'))
        self.scorer_sell_threshold = float(self.get_env_variable('SCORER_SELL_THRESHOLD', required=False, default='0.42'))
        self.min_confidence = float(self.get_env_variable('MIN_CONFIDENCE', required=False, default='0.15'))

        # 价格窗口配置
        self.main_price_min = float(self.get_env_variable('MAIN_PRICE_MIN', required=False, default='0.50'))
        self.main_price_max = float(self.get_env_variable('MAIN_PRICE_MAX', required=False, default='0.65'))
        self.hedge_price_min = float(self.get_env_variable('HEDGE_PRICE_MIN', required=False, default='0.05'))
        self.hedge_price_max = float(self.get_env_variable('HEDGE_PRICE_MAX', required=False, default='0.15'))

        # 对冲配置
        self.hedge_first = self.get_env_variable('HEDGE_FIRST', required=False, default='true').lower() == 'true'
        self.fee_rate = float(self.get_env_variable('FEE_RATE', required=False, default='0.02'))

        # 风控配置
        self.daily_loss_limit_usdc = float(self.get_env_variable('DAILY_LOSS_LIMIT_USDC', required=False, default='20'))
        self.daily_trade_limit = int(self.get_env_variable('DAILY_TRADE_LIMIT', required=False, default='20'))
        self.consecutive_loss_limit = int(self.get_env_variable('CONSECUTIVE_LOSS_LIMIT', required=False, default='3'))

        # 时间窗口配置（秒）
        self.hard_stop_sec = int(self.get_env_variable('HARD_STOP_SEC', required=False, default='30'))
        self.min_secs_main = int(self.get_env_variable('MIN_SECS_MAIN', required=False, default='90'))
        self.min_secs_hedge = int(self.get_env_variable('MIN_SECS_HEDGE', required=False, default='60'))

        # 市场质量配置
        self.max_spread = float(self.get_env_variable('MAX_SPREAD', required=False, default='0.05'))
        self.min_depth = float(self.get_env_variable('MIN_DEPTH', required=False, default='50'))

        # 下注规模（USDC）
        self.bet_size_usdc = float(self.get_env_variable('BET_SIZE_USDC', required=False, default='3.0'))

        # ---- Polymarket CLOB 实盘交易凭证 ----
        # CLOB 主机（一般无需修改）
        self.clob_host = self.get_env_variable('CLOB_HOST', required=False, default='https://clob.polymarket.com')
        # 链 ID：Polygon 主网 137
        self.chain_id = int(self.get_env_variable('CHAIN_ID', required=False, default='137'))
        # 用于签名订单的私钥（控制 EOA 钱包）
        self.private_key = self.get_env_variable('PRIVATE_KEY', required=False, default='')
        # 资金钱包地址：
        #   - signature_type=0 (EOA)            -> 留空或填 EOA 地址
        #   - signature_type=1 (POLY_PROXY)     -> Polymarket 网站显示的 Proxy 地址
        #   - signature_type=2 (POLY_GNOSIS_SAFE) -> Gnosis Safe 地址
        self.funder = self.get_env_variable('FUNDER', required=False, default='')
        # 签名类型：0=EOA, 1=POLY_PROXY, 2=POLY_GNOSIS_SAFE
        _sig = self.get_env_variable('SIGNATURE_TYPE', required=False, default='1')
        try:
            self.signature_type = int(_sig)
        except ValueError:
            self.signature_type = 1
        # 可选：直接提供 L2 API creds（不提供则首次启动自动派生）
        self.clob_api_key = self.get_env_variable('CLOB_API_KEY', required=False, default='')
        self.clob_api_secret = self.get_env_variable('CLOB_API_SECRET', required=False, default='')
        self.clob_api_passphrase = self.get_env_variable('CLOB_API_PASSPHRASE', required=False, default='')

        # ---- 末端狙击策略配置 ----
        self.sniper_entry_secs = int(self.get_env_variable('SNIPER_ENTRY_SECS', required=False, default='30'))
        self.sniper_price_min = float(self.get_env_variable('SNIPER_PRICE_MIN', required=False, default='0.55'))
        self.sniper_price_max = float(self.get_env_variable('SNIPER_PRICE_MAX', required=False, default='0.60'))
        self.sniper_min_delta_bps = float(self.get_env_variable('SNIPER_MIN_DELTA_BPS', required=False, default='2.0'))
        self.sniper_momentum_secs = int(self.get_env_variable('SNIPER_MOMENTUM_SECS', required=False, default='30'))
        self.sniper_kelly_fraction = float(self.get_env_variable('SNIPER_KELLY_FRACTION', required=False, default='0.5'))

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
        }
