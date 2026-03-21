import math
from typing import Dict, List, Optional, Any, Tuple
from lib.utils import log_info, log_error, log_warn


class MomentumHedgeStrategy:
    """
    动量跟踪 + 最优对冲投注策略
    Momentum tracking with Kelly-optimal hedge betting strategy

    核心思想：不预测方向，等市场自己表态。当一方价格≥阈值时，
    跟随强势方下注，同时用数学最优比例对冲弱势方。

    Core idea: Don't predict direction. Wait for the market to show
    a clear favorite (price >= threshold), then bet on the favorite
    with a Kelly-optimal hedge on the underdog.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize strategy with config dict.

        Config params (all with env var support):
        - trigger_threshold: 触发价格阈值 (default 0.70)
        - total_bet_size: 每个市场总投注金额 (default 4 USDC)
        - min_remaining_seconds: 最少剩余秒数 (default 60)
        - max_trigger_price: 不追太高的价格 (default 0.85)
        - use_dynamic_ratio: 是否动态计算对冲比例 (default True)
        - fixed_hedge_ratio: 固定对冲比例,仅当dynamic=False时 (default 0.33)
        - win_rate_slope: 胜率斜率系数 (default 1.0)
        """
        self.config = config
        self.bet_placed_markets: set = set()  # 已下注的市场ID集合 / Already-bet market IDs

    def estimate_win_rate(self, price: float) -> float:
        """
        估计强势方胜率 W(P)
        Estimate win probability of the favorite given its token price.

        使用线性模型：W = 0.5 + (P - 0.5) * slope
        With slope=1.0: W(P) = P, capped at [0.55, 0.95].
        """
        slope = float(self.config.get('win_rate_slope', 1.0))
        w = 0.5 + (price - 0.5) * slope
        # Cap within reasonable bounds 限制在合理范围内
        return max(0.55, min(0.95, w))

    def calculate_optimal_hedge_ratio(self, price: float) -> float:
        """
        计算 Kelly 最优对冲比例
        Calculate Kelly-optimal hedge ratio by maximising the log growth rate.

        G(r) = W * ln(win_factor) + (1-W) * ln(lose_factor)

        where:
          win_factor  = 1 / (P * (1 + r))   — relative return when favorite wins
          lose_factor = r / ((1-P) * (1+r)) — relative return when underdog wins

        Grid-searches r ∈ [0.05, 0.50] (step 0.01) and returns the r* that
        maximises G.  Falls back to the configured fixed_hedge_ratio if no
        valid r is found.
        """
        W = self.estimate_win_rate(price)
        P = price

        best_r = float(self.config.get('fixed_hedge_ratio', 0.33))
        best_G = float('-inf')

        r = 0.05
        while r <= 0.50 + 1e-9:
            # Return factors (must be positive for ln to be defined)
            win_factor = 1.0 / (P * (1.0 + r))        # simplified from (1/P)/(1+r)
            lose_factor = r / ((1.0 - P) * (1.0 + r))  # simplified from rP/((1-P)(1+r))

            if win_factor > 0 and lose_factor > 0:
                G = W * math.log(win_factor) + (1.0 - W) * math.log(lose_factor)
                if G > best_G:
                    best_G = G
                    best_r = round(r, 2)

            r = round(r + 0.01, 2)

        return best_r

    def check_trigger(self, up_price: float, down_price: float) -> Optional[Dict]:
        """
        检查是否触发投注条件
        Check if market prices have diverged enough to trigger a bet.

        Returns None if no trigger, or a dict:
        {
            'favorite': 'UP' or 'DOWN',
            'favorite_price': float,
            'underdog_price': float,
            'hedge_ratio': float,
            'estimated_win_rate': float,
        }
        """
        threshold = float(self.config.get('trigger_threshold', 0.70))
        max_price = float(self.config.get('max_trigger_price', 0.85))

        for favorite, fav_price, und_price in [
            ('UP', up_price, down_price),
            ('DOWN', down_price, up_price),
        ]:
            if threshold <= fav_price <= max_price and und_price <= (1.0 - threshold):
                use_dynamic = self.config.get('use_dynamic_ratio', True)
                if isinstance(use_dynamic, str):
                    use_dynamic = use_dynamic.lower() != 'false'

                if use_dynamic:
                    hedge_ratio = self.calculate_optimal_hedge_ratio(fav_price)
                else:
                    hedge_ratio = float(self.config.get('fixed_hedge_ratio', 0.33))

                win_rate = self.estimate_win_rate(fav_price)

                return {
                    'favorite': favorite,
                    'favorite_price': fav_price,
                    'underdog_price': und_price,
                    'hedge_ratio': hedge_ratio,
                    'estimated_win_rate': win_rate,
                }

        return None

    def calculate_bet_sizes(self, total_bet: float, hedge_ratio: float) -> Tuple[float, float]:
        """
        计算主注和对冲注金额
        Calculate main-bet and hedge-bet USDC amounts.

        main_bet  = total_bet / (1 + hedge_ratio)
        hedge_bet = total_bet * hedge_ratio / (1 + hedge_ratio)
        """
        main_bet = total_bet / (1.0 + hedge_ratio)
        hedge_bet = total_bet * hedge_ratio / (1.0 + hedge_ratio)
        return main_bet, hedge_bet

    def generate_orders(
        self,
        up_price: float,
        down_price: float,
        up_token_id: str,
        down_token_id: str,
        market_id: str,
        market_remaining_seconds: float,
    ) -> List[Dict[str, Any]]:
        """
        生成订单列表
        Generate the order list based on current market state.

        Steps:
        1. Check if already bet on this market → return []
        2. Check remaining time >= min_remaining_seconds → return []
        3. Call check_trigger() → if None, return []
        4. Calculate bet sizes
        5. Return list of 2 orders: main bet + hedge bet
        6. Mark market as bet

        Each order dict:
        {
            'side': 'BUY',
            'outcome': 'Up' or 'Down',
            'token_id': str,
            'price': float,   # ask price to use
            'size': float,    # number of shares = USDC_amount / price
            'role': 'main' or 'hedge',
            'hedge_ratio': float,
        }
        """
        # 1. 每个市场只下注一次 / One bet per market
        if market_id in self.bet_placed_markets:
            return []

        # 2. 剩余时间检查 / Remaining time check
        min_secs = float(self.config.get('min_remaining_seconds', 60))
        if market_remaining_seconds < min_secs:
            log_warn(
                f"⏳ 市场剩余时间 {market_remaining_seconds:.0f}s < 最低要求 {min_secs:.0f}s，跳过"
                f" | Remaining {market_remaining_seconds:.0f}s < min {min_secs:.0f}s, skip"
            )
            return []

        # 3. 触发条件检查 / Trigger condition check
        trigger = self.check_trigger(up_price, down_price)
        if trigger is None:
            return []

        favorite = trigger['favorite']
        fav_price = trigger['favorite_price']
        und_price = trigger['underdog_price']
        hedge_ratio = trigger['hedge_ratio']
        win_rate = trigger['estimated_win_rate']

        total_bet = float(self.config.get('total_bet_size', 4.0))
        main_bet_usdc, hedge_bet_usdc = self.calculate_bet_sizes(total_bet, hedge_ratio)

        # Determine token IDs and outcomes
        if favorite == 'UP':
            main_token_id = up_token_id
            hedge_token_id = down_token_id
            main_outcome = 'Up'
            hedge_outcome = 'Down'
        else:
            main_token_id = down_token_id
            hedge_token_id = up_token_id
            main_outcome = 'Down'
            hedge_outcome = 'Up'

        # Shares = USDC amount / token price
        main_shares = main_bet_usdc / fav_price
        hedge_shares = hedge_bet_usdc / und_price

        log_info(
            f"🎯 触发动量对冲策略 | Momentum hedge triggered\n"
            f"   强势方 Favorite: {favorite} @ {fav_price:.4f} (胜率 win-rate: {win_rate:.2%})\n"
            f"   弱势方 Underdog: {und_price:.4f}\n"
            f"   对冲比例 hedge ratio r={hedge_ratio:.2f}\n"
            f"   主注 main: {main_bet_usdc:.2f} USDC → {main_shares:.4f} shares\n"
            f"   对冲 hedge: {hedge_bet_usdc:.2f} USDC → {hedge_shares:.4f} shares"
        )

        orders = [
            {
                'side': 'BUY',
                'outcome': main_outcome,
                'token_id': main_token_id,
                'price': fav_price,
                'size': main_shares,
                'role': 'main',
                'hedge_ratio': hedge_ratio,
            },
            {
                'side': 'BUY',
                'outcome': hedge_outcome,
                'token_id': hedge_token_id,
                'price': und_price,
                'size': hedge_shares,
                'role': 'hedge',
                'hedge_ratio': hedge_ratio,
            },
        ]

        # 6. 标记已下注 / Mark market as bet
        self.bet_placed_markets.add(market_id)

        return orders

    def get_expected_pnl(
        self,
        favorite_price: float,
        hedge_ratio: float,
        total_bet: float,
    ) -> Dict:
        """
        计算预期盈亏（用于日志和监控）
        Calculate expected P&L for logging/monitoring.

        Returns:
        {
            'win_profit': float,      # net profit when favorite wins
            'lose_loss': float,       # net loss when favorite loses (negative)
            'expected_value': float,  # W * win_profit + (1-W) * lose_loss
            'kelly_growth_rate': float,
        }
        """
        P = favorite_price
        r = hedge_ratio
        W = self.estimate_win_rate(P)

        main_bet, hedge_bet = self.calculate_bet_sizes(total_bet, r)

        # 强势方赢 / Favorite wins
        # win = main_bet/P - main_bet - hedge_bet = main_bet * (1/P - 1 - r)
        win_profit = main_bet / P - main_bet - hedge_bet

        # 强势方输 / Favorite loses
        # lose = hedge_bet/(1-P) - main_bet - hedge_bet = main_bet * (rP/(1-P) - 1)
        lose_outcome = hedge_bet / (1.0 - P) - main_bet - hedge_bet

        expected_value = W * win_profit + (1.0 - W) * lose_outcome

        # Kelly growth rate
        try:
            win_factor = 1.0 / (P * (1.0 + r))
            lose_factor = r / ((1.0 - P) * (1.0 + r))
            kelly_growth = W * math.log(win_factor) + (1.0 - W) * math.log(lose_factor)
        except (ValueError, ZeroDivisionError):
            kelly_growth = float('-inf')

        return {
            'win_profit': win_profit,
            'lose_loss': lose_outcome,
            'expected_value': expected_value,
            'kelly_growth_rate': kelly_growth,
        }

    def reset_for_new_day(self):
        """重置每日状态 / Reset daily state"""
        self.bet_placed_markets.clear()
        log_info("🔄 动量对冲策略每日状态已重置 | Momentum hedge daily state reset")
