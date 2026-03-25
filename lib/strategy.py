from typing import List, Dict, Any, Optional, Tuple
from lib.utils import round_to_tick, log_info, log_warn

class GridStrategy:
    """Grid Trading Strategy"""
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize grid strategy with config"""
        self.config = config
        self.grid_levels = []
        self.orders = []
    
    def validate_config(self, tick_size: float, min_order_size: float):
        """Validate strategy configuration"""
        order_size = self.config.get('order_size', 5)
        grid_step = self.config.get('grid_step', 0.02)
        
        if order_size < min_order_size:
            raise ValueError(f"order_size ({order_size}) < min_order_size ({min_order_size})")
        
        # Check if grid_step is multiple of tick_size
        steps_in_ticks = round(grid_step / tick_size)
        step_in_ticks = steps_in_ticks * tick_size
        
        if abs(step_in_ticks - grid_step) > 1e-10:
            raise ValueError(f"grid_step ({grid_step}) is not multiple of tick_size ({tick_size})")
        
        log_info("✅ Strategy config validated")
    
    def generate_grid_levels(
        self,
        mid_price: float,
        tick_size: float,
        grid_step: float,
        levels_each_side: int
    ) -> List[float]:
        """Generate grid price levels"""
        levels = []
        
        # Lower levels
        for i in range(levels_each_side, 0, -1):
            price = round_to_tick(mid_price - grid_step * i, tick_size)
            if tick_size <= price <= 1 - tick_size:
                levels.append(price)
        
        # Center level
        levels.append(round_to_tick(mid_price, tick_size))
        
        # Upper levels
        for i in range(1, levels_each_side + 1):
            price = round_to_tick(mid_price + grid_step * i, tick_size)
            if tick_size <= price <= 1 - tick_size:
                levels.append(price)
        
        self.grid_levels = levels
        log_info(f"✅ Generated {len(levels)} grid levels")
        return levels
    
    def generate_order_plan(
        self,
        up_mid: float,
        down_mid: float,
        up_token: str,
        down_token: str,
        trade_both: bool = True
    ) -> List[Dict[str, Any]]:
        """Generate order plan based on grid levels"""
        plan = []
        order_size = self.config.get('order_size', 5)
        
        # Up side orders
        for price in self.grid_levels:
            if price < up_mid:
                plan.append({
                    'side': 'BUY',
                    'outcome': 'Up',
                    'token_id': up_token,
                    'price': price,
                    'size': order_size
                })
            elif price > up_mid:
                plan.append({
                    'side': 'SELL',
                    'outcome': 'Up',
                    'token_id': up_token,
                    'price': price,
                    'size': order_size
                })
        
        # Down side orders
        if trade_both:
            for price in self.grid_levels:
                if price < down_mid:
                    plan.append({
                        'side': 'BUY',
                        'outcome': 'Down',
                        'token_id': down_token,
                        'price': price,
                        'size': order_size
                    })
                elif price > down_mid:
                    plan.append({
                        'side': 'SELL',
                        'outcome': 'Down',
                        'token_id': down_token,
                        'price': price,
                        'size': order_size
                    })
        
        self.orders = plan
        log_info(f"✅ Generated {len(plan)} orders")
        return plan
    
    def get_order_plan(self) -> List[Dict[str, Any]]:
        """Get sorted order plan"""
        return sorted(
            self.orders,
            key=lambda o: (o['outcome'], o['price'])
        )


class ProductionDecisionStrategy:
    """
    Production-grade decision layer that combines DirectionScorer output with
    price-window filters to decide whether to enter a main/hedge pair trade.

    Parameters
    ----------
    min_confidence : float
        Minimum scorer confidence required to trade (default 0.15).
    main_price_min / main_price_max : float
        Allowed price window for the main (YES) position.
    hedge_price_min / hedge_price_max : float
        Allowed price window for the hedge (NO) position.
    """

    def __init__(
        self,
        min_confidence: float = 0.15,
        main_price_min: float = 0.50,
        main_price_max: float = 0.65,
        hedge_price_min: float = 0.05,
        hedge_price_max: float = 0.15,
    ):
        self.min_confidence = min_confidence
        self.main_price_min = main_price_min
        self.main_price_max = main_price_max
        self.hedge_price_min = hedge_price_min
        self.hedge_price_max = hedge_price_max

    def decide(
        self,
        scorer_result: Dict[str, Any],
        yes_mid: float,
        no_mid: float,
    ) -> Dict[str, Any]:
        """
        Decide whether to enter a trade based on scorer output and price windows.

        Parameters
        ----------
        scorer_result : dict
            Output from DirectionScorer.compute_final_score().
        yes_mid : float
            Mid-price of the YES token.
        no_mid : float
            Mid-price of the NO token.

        Returns
        -------
        dict with keys:
            action        : str   'ENTER' | 'SKIP'
            reason        : str   Human-readable reason for the decision.
            direction     : str   'BUY_YES' | 'BUY_NO' | 'SKIP'
            probability   : float
            confidence    : float
            main_price    : float  Suggested main bet price.
            hedge_price   : float  Suggested hedge bet price.
        """
        direction = scorer_result.get("direction", "SKIP")
        probability = scorer_result.get("probability", 0.5)
        confidence = scorer_result.get("confidence", 0.0)

        # 1. Confidence gate
        if confidence < self.min_confidence:
            reason = (
                f"confidence {confidence:.4f} < min_confidence {self.min_confidence}"
            )
            log_warn(f"[Strategy] SKIP — {reason}")
            return self._skip(reason, direction, probability, confidence, yes_mid, no_mid)

        # 2. Direction must not be SKIP from the scorer
        if direction == "SKIP":
            reason = "scorer returned SKIP"
            log_warn(f"[Strategy] SKIP — {reason}")
            return self._skip(reason, direction, probability, confidence, yes_mid, no_mid)

        # 3. Price window filters
        # For BUY_YES: main=YES, hedge=NO
        # For BUY_NO:  main=NO,  hedge=YES
        if direction == "BUY_YES":
            main_price = yes_mid
            hedge_price = no_mid
        else:
            main_price = no_mid
            hedge_price = yes_mid

        if not (self.main_price_min <= main_price <= self.main_price_max):
            reason = (
                f"main_price {main_price:.4f} outside window "
                f"[{self.main_price_min}, {self.main_price_max}]"
            )
            log_warn(f"[Strategy] SKIP — {reason}")
            return self._skip(reason, direction, probability, confidence, yes_mid, no_mid)

        if not (self.hedge_price_min <= hedge_price <= self.hedge_price_max):
            reason = (
                f"hedge_price {hedge_price:.4f} outside window "
                f"[{self.hedge_price_min}, {self.hedge_price_max}]"
            )
            log_warn(f"[Strategy] SKIP — {reason}")
            return self._skip(reason, direction, probability, confidence, yes_mid, no_mid)

        reason = (
            f"direction={direction} prob={probability:.4f} "
            f"conf={confidence:.4f} main_price={main_price:.4f} "
            f"hedge_price={hedge_price:.4f}"
        )
        log_info(f"[Strategy] ENTER — {reason}")
        return {
            "action": "ENTER",
            "reason": reason,
            "direction": direction,
            "probability": probability,
            "confidence": confidence,
            "main_price": main_price,
            "hedge_price": hedge_price,
        }

    @staticmethod
    def _skip(
        reason: str,
        direction: str,
        probability: float,
        confidence: float,
        yes_mid: float,
        no_mid: float,
    ) -> Dict[str, Any]:
        return {
            "action": "SKIP",
            "reason": reason,
            "direction": direction,
            "probability": probability,
            "confidence": confidence,
            "main_price": yes_mid,
            "hedge_price": no_mid,
        }
