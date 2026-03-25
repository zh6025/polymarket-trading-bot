#!/usr/bin/env python3
import sys
import time
import logging
from lib.config import Config
from lib.utils import log_info, log_error, log_warn
from lib.polymarket_client import PolymarketClient
from lib.direction_scorer import DirectionScorer
from lib.decision import make_trade_decision
from lib.bot_state import BotState
from lib.hedge_formula import compute_optimal_hedge

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def run_trading_cycle(config: Config, client: PolymarketClient,
                      scorer: DirectionScorer, state: BotState):
    """单次交易周期：检查条件 → 获取信号 → 决策 → 执行 → 记录"""

    # 1. 检查是否允许交易
    can, reason = state.can_trade(
        daily_loss_limit=config.daily_loss_limit_usdc,
        daily_trade_limit=config.daily_trade_limit,
        consec_loss_limit=config.consecutive_loss_limit,
    )
    if not can:
        log_warn(f"⏸ 交易暂停: {reason}")
        return

    # 2. 获取当前市场数据
    try:
        markets = client.get_markets()
        btc_markets = client.filter_btc_markets(markets) if markets else []
        if not btc_markets:
            log_warn("⚠️  未找到 BTC 5分钟市场，跳过本周期")
            return
        market = btc_markets[0]
    except Exception as e:
        log_error(f"获取市场数据失败: {e}")
        return

    # 3. 解析市场价格
    market_id = market.get('id', '')
    up_price = float(market.get('up_price', 0.5))
    down_price = float(market.get('down_price', 0.5))
    spread = abs(up_price + down_price - 1.0)
    depth = float(market.get('depth', 0))
    remaining_seconds = int(market.get('remaining_seconds', 0))

    # 4. 获取方向评分
    if config.scorer_enabled:
        scorer_result = scorer.compute_final_score(
            yes_depth=market.get('yes_depth', 0),
            no_depth=market.get('no_depth', 0),
        )
    else:
        # 回退到简单mid-price ratio（向后兼容）
        mid_ratio = up_price / max(up_price + down_price, 1e-9)
        if mid_ratio > config.scorer_buy_threshold:
            direction = 'BUY_YES'
        elif mid_ratio < config.scorer_sell_threshold:
            direction = 'BUY_NO'
        else:
            direction = 'SKIP'
        scorer_result = {
            'direction': direction,
            'prob_up': mid_ratio,
            'total_score': 0,
        }

    log_info(f"📊 信号: direction={scorer_result.get('direction')} "
             f"prob_up={scorer_result.get('prob_up', 0):.4f} "
             f"score={scorer_result.get('total_score', 0):.2f}")

    # 5. 交易决策
    decision = make_trade_decision(
        remaining_seconds=remaining_seconds,
        up_price=up_price,
        down_price=down_price,
        spread=spread,
        depth=depth,
        scorer_result=scorer_result,
        hard_stop_sec=config.hard_stop_sec,
        min_secs_main=config.min_secs_main,
        min_secs_hedge=config.min_secs_hedge,
        main_price_min=config.main_price_min,
        main_price_max=config.main_price_max,
        hedge_price_min=config.hedge_price_min,
        hedge_price_max=config.hedge_price_max,
        max_spread=config.max_spread,
        min_depth=config.min_depth,
        min_confidence=config.min_confidence,
        fee=config.fee_rate,
    )

    log_info(f"🎯 决策: action={decision['action']} reason={decision['reason']}")

    if decision['action'] == 'SKIP':
        return

    # 6. 执行交易（先对冲后主仓）
    main_price = decision['main_price']
    direction = decision['direction']
    bet_size = config.bet_size_usdc

    if decision['action'] == 'ENTER_MAIN_AND_HEDGE' and config.hedge_first:
        hedge_price = decision['hedge_price']
        hedge_result = compute_optimal_hedge(
            P_m=main_price,
            Q_m=bet_size,
            P_h=hedge_price,
            fee=config.fee_rate,
        )

        if hedge_result['feasible']:
            hedge_qty = hedge_result['hedge_quantity']
            hedge_cost = hedge_result['hedge_cost']
            hedge_direction = 'NO' if direction == 'UP' else 'YES'

            log_info(f"🛡 步骤1: 先挂对冲单 {hedge_direction} @ {hedge_price:.3f} x {hedge_qty:.2f} (成本={hedge_cost:.4f} USDC)")

            # 模拟或真实下对冲单
            if not config.dry_run:
                try:
                    hedge_token = market.get('no_token_id' if direction == 'UP' else 'yes_token_id', '')
                    if not hedge_token:
                        log_error("对冲 token_id 为空，跳过本周期")
                        return
                    client.place_order(
                        token_id=hedge_token,
                        side='buy',
                        price=hedge_price,
                        size=hedge_qty,
                    )
                    log_info(f"✅ 对冲单已提交")
                except Exception as e:
                    log_error(f"对冲单失败，跳过本周期: {e}")
                    return
            else:
                log_info(f"🔬 DRY-RUN: 对冲单跳过实际提交")

    # 步骤2: 下主仓
    main_direction = 'YES' if direction == 'UP' else 'NO'
    log_info(f"📈 步骤2: 下主仓 {main_direction} @ {main_price:.3f} x {bet_size:.2f} USDC")

    if not config.dry_run:
        try:
            main_token = market.get('yes_token_id' if direction == 'UP' else 'no_token_id', '')
            if not main_token:
                log_error("主仓 token_id 为空，跳过本周期")
                return
            client.place_order(
                token_id=main_token,
                side='buy',
                price=main_price,
                size=bet_size,
            )
            log_info(f"✅ 主仓单已提交")
        except Exception as e:
            log_error(f"主仓单失败: {e}")
            return
    else:
        log_info(f"🔬 DRY-RUN: 主仓单跳过实际提交")

    # 7. 记录交易（DRY-RUN 记录虚拟损益 0，等待结算）
    state.record_trade(pnl=0.0)
    state.save()
    log_info(f"💾 交易记录已保存, 今日交易={state.daily_trade_count}")


def main():
    print("""
╔═══════════════════════════════════════════════╗
║     Polymarket Trading Bot - BTC 5m Market    ║
║        DirectionScorer + Hedge Formula        ║
╚═══════════════════════════════════════════════╝
    """)

    try:
        # 加载配置
        config = Config()
        log_info(f"配置加载完成: strategy={config.strategy} "
                 f"trading_enabled={config.trading_enabled} "
                 f"dry_run={config.dry_run}")

        if not config.trading_enabled:
            log_warn("⚠️  TRADING_ENABLED=false，机器人以监控模式运行（不会下单）")
            log_warn("    设置 TRADING_ENABLED=true 以开启真实交易")

        # 加载状态（支持crash recovery）
        state = BotState.load()
        state.trading_enabled = config.trading_enabled

        # 初始化客户端和评分器
        client = PolymarketClient()
        scorer = DirectionScorer(
            steepness=config.scorer_steepness,
            buy_threshold=config.scorer_buy_threshold,
            sell_threshold=config.scorer_sell_threshold,
        )

        log_info(f"📊 状态: PnL=${state.total_pnl:.2f} 今日=${state.daily_pnl:.2f} "
                 f"交易次数={state.daily_trade_count}")

        # 主循环
        poll_interval_sec = config.polling_interval / 1000
        log_info(f"🚀 启动主循环，轮询间隔={poll_interval_sec:.1f}s")

        while True:
            try:
                run_trading_cycle(config, client, scorer, state)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                log_error(f"周期异常（已捕获，继续运行）: {e}")

            time.sleep(poll_interval_sec)

    except KeyboardInterrupt:
        log_info("⛔ 收到中断信号，正常退出")
        sys.exit(0)
    except Exception as e:
        log_error(f"❌ Fatal error: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
