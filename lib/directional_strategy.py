from typing import Dict, List, Optional, Any
from lib.btc_price_feed import BtcPriceFeed
from lib.utils import log_info, log_error, log_warn


class DirectionalStrategy:
    """
    BTC 价格驱动的方向性投注策略（适用于 5 分钟二元市场）。
    BTC price-driven directional strategy for 5-minute binary markets.

    核心逻辑 / Core logic:
    - 从 Binance 获取真实 BTC/USDT 1 分钟 K 线数据
    - 使用 EMA 交叉（快线 vs 慢线）判断短期趋势方向
    - 使用 ATR 过滤低波动期（波动不够大时跳过）
    - 每个市场只投一边（UP 或 DOWN），绝不同时做双边
    - 只在赔率有利（ask 价格低于阈值）时才入场
    - 只在市场开放早期（前 N 秒）入场，避免临近结算时入场
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.btc_feed = BtcPriceFeed()

        # EMA 周期配置 / EMA period configuration
        self.ema_fast_period = int(config.get("ema_fast_period", 3))
        self.ema_slow_period = int(config.get("ema_slow_period", 8))

        # ATR 配置 / ATR configuration
        self.atr_period = int(config.get("atr_period", 10))
        # ATR 阈值比例（占当前价格的比例）。
        # 0.0003 = 0.03%：BTC ≈ $90000 时至少需 ~$27 的 ATR 才下注。
        # 该阈值过滤低波动期（EMA 交叉信号在低波动时不可靠）。
        # Filters out low-volatility periods where EMA crossover signals are unreliable.
        self.atr_threshold_pct = float(config.get("atr_threshold_pct", 0.0003))

        # 入场价格上限（ask 超过此值不入场）/ Max ask price to enter
        self.max_entry_price = float(config.get("max_entry_price", 0.55))

        # 每笔下注金额 / Bet size per trade (USDC)
        self.bet_size = float(config.get("bet_size", 5))

        # 市场生命周期内允许入场的时间窗口（秒）/ Entry window in seconds from market open
        self.market_entry_window = int(config.get("market_entry_window", 120))

        # EMA 信号缓冲区：避免 EMA 几乎相等时频繁切换方向
        # Signal buffer (0.02%): prevents signal flip-flop when EMAs are nearly equal
        self._signal_buffer = float(config.get("ema_signal_buffer", 0.0002))

    def calculate_ema(self, prices: List[float], period: int) -> Optional[float]:
        """
        计算指数移动平均线（EMA）。
        Calculate Exponential Moving Average.

        Returns None if not enough data.
        """
        if len(prices) < period:
            return None

        k = 2.0 / (period + 1)
        ema = prices[0]
        for price in prices[1:]:
            ema = price * k + ema * (1 - k)
        return ema

    def calculate_atr(self, klines: List, period: int) -> float:
        """
        计算平均真实波幅（ATR）。
        Calculate Average True Range from OHLCV candle data.

        Kline format (Binance): [open_time, open, high, low, close, volume, ...]
        Indices:                  0          1      2     3    4      5
        Returns 0.0 if not enough data.
        """
        if len(klines) < period + 1:
            return 0.0

        true_ranges = []
        for i in range(1, len(klines)):
            high = float(klines[i][2])
            low = float(klines[i][3])
            prev_close = float(klines[i - 1][4])

            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close),
            )
            true_ranges.append(tr)

        # 使用最近 period 根 K 线的简单平均 / Simple average of last N bars
        recent = true_ranges[-period:]
        return sum(recent) / len(recent) if recent else 0.0

    def generate_signal(self) -> str:
        """
        生成交易信号：'UP', 'DOWN', 或 'SKIP'。
        Generate trading signal based on BTC price data.

        Logic:
        1. 获取最近 30 根 1 分钟 BTC/USDT K 线 / Fetch 30 recent 1-min candles
        2. 提取收盘价，计算 EMA(fast) 和 EMA(slow) / Extract closes, compute EMAs
        3. 计算 ATR(period)，与阈值比较 / Compute ATR vs threshold
        4. ATR 太低 → SKIP（低波动，预测不可靠）/ Low ATR → SKIP
        5. EMA_fast > EMA_slow × (1 + buffer) → UP
        6. EMA_fast < EMA_slow × (1 - buffer) → DOWN
        7. 否则 → SKIP / Otherwise → SKIP
        """
        klines = self.btc_feed.get_btc_klines(interval="1m", limit=30)
        if not klines:
            log_warn("⚠️  无法获取 BTC K线数据，跳过本次信号生成")
            return "SKIP"

        closes = [float(k[4]) for k in klines]

        ema_fast = self.calculate_ema(closes, self.ema_fast_period)
        ema_slow = self.calculate_ema(closes, self.ema_slow_period)

        if ema_fast is None or ema_slow is None:
            log_warn("⚠️  K线数据不足，无法计算 EMA，跳过")
            return "SKIP"

        atr = self.calculate_atr(klines, self.atr_period)
        current_price = closes[-1]
        min_atr = current_price * self.atr_threshold_pct

        log_info(
            f"📊 BTC 信号分析: 价格={current_price:.2f} "
            f"EMA{self.ema_fast_period}={ema_fast:.2f} "
            f"EMA{self.ema_slow_period}={ema_slow:.2f} "
            f"ATR={atr:.2f} 最小ATR={min_atr:.2f}"
        )

        # ATR 过滤：波动太低时不交易 / Skip when market is too quiet
        if atr < min_atr:
            log_info("📉 ATR 低于阈值，波动不足，跳过 (SKIP)")
            return "SKIP"

        # EMA 交叉信号 / EMA crossover signal
        upper_band = ema_slow * (1 + self._signal_buffer)
        lower_band = ema_slow * (1 - self._signal_buffer)

        if ema_fast > upper_band:
            log_info(f"🟢 信号: UP（EMA{self.ema_fast_period} 上穿 EMA{self.ema_slow_period}）")
            return "UP"
        elif ema_fast < lower_band:
            log_info(f"🔴 信号: DOWN（EMA{self.ema_fast_period} 下穿 EMA{self.ema_slow_period}）")
            return "DOWN"
        else:
            log_info("⚪ 信号: SKIP（EMA 交叉不明确）")
            return "SKIP"

    def decide_bet(
        self,
        signal: str,
        up_token_ask: float,
        down_token_ask: float,
        up_token_id: str = "",
        down_token_id: str = "",
    ) -> Optional[Dict[str, Any]]:
        """
        根据信号和当前 ask 价格决定是否下注，以及下注方向。
        Decide what to bet given signal and current token ask prices.

        Returns a bet dict or None.
        Rules:
        - SKIP 信号 → None
        - UP 信号且 up_ask ≤ max_entry_price → BUY UP
        - DOWN 信号且 down_ask ≤ max_entry_price → BUY DOWN
        - 赔率不理想 → None
        """
        if signal == "SKIP":
            log_info("⏭️  信号为 SKIP，不下注")
            return None

        if signal == "UP":
            if up_token_ask <= self.max_entry_price:
                log_info(
                    f"✅ 决策: 买入 UP @ ask={up_token_ask:.4f} "
                    f"（≤ 上限 {self.max_entry_price}）"
                )
                return {
                    "side": "BUY",
                    "outcome": "UP",
                    "token_id": up_token_id,
                    "price": up_token_ask,
                    "size": self.bet_size,
                }
            else:
                log_info(
                    f"🚫 UP ask={up_token_ask:.4f} 超过上限 {self.max_entry_price}，跳过"
                )
                return None

        if signal == "DOWN":
            if down_token_ask <= self.max_entry_price:
                log_info(
                    f"✅ 决策: 买入 DOWN @ ask={down_token_ask:.4f} "
                    f"（≤ 上限 {self.max_entry_price}）"
                )
                return {
                    "side": "BUY",
                    "outcome": "DOWN",
                    "token_id": down_token_id,
                    "price": down_token_ask,
                    "size": self.bet_size,
                }
            else:
                log_info(
                    f"🚫 DOWN ask={down_token_ask:.4f} 超过上限 {self.max_entry_price}，跳过"
                )
                return None

        return None

    def should_enter_market(self, market_created_timestamp) -> bool:
        """
        判断是否在市场开放的早期时间窗口内。
        Only enter within the first ~market_entry_window seconds of the market lifecycle.

        market_created_timestamp: Unix timestamp (int/float) or datetime object.
        Returns True if we are still within the entry window, False otherwise.
        """
        from datetime import datetime, timezone

        if market_created_timestamp is None:
            # 无法确定市场年龄时，默认允许入场 / Allow entry if timestamp unknown
            return True

        try:
            if isinstance(market_created_timestamp, (int, float)):
                market_open = datetime.fromtimestamp(
                    market_created_timestamp, tz=timezone.utc
                )
            else:
                # datetime object - make it timezone-aware if naive
                market_open = market_created_timestamp
                if market_open.tzinfo is None:
                    market_open = market_open.replace(tzinfo=timezone.utc)

            now = datetime.now(tz=timezone.utc)
            age_seconds = (now - market_open).total_seconds()

            if age_seconds <= self.market_entry_window:
                log_info(
                    f"⏱️  市场开放已 {age_seconds:.0f}s，在入场窗口内 "
                    f"（≤ {self.market_entry_window}s）"
                )
                return True
            else:
                log_info(
                    f"⏳ 市场开放已 {age_seconds:.0f}s，超过入场窗口 "
                    f"（{self.market_entry_window}s），跳过"
                )
                return False
        except Exception as e:
            log_error(f"❌ 判断市场入场窗口失败: {e}")
            return True
