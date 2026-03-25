# Polymarket BTC 5分钟交易机器人

自动交易 Polymarket BTC Up/Down 5分钟市场，集成9维度方向评分、精确对冲公式和全链路风控。

## 架构

```
bot_runner.py          # 主入口：主循环 + 周期协调
lib/
  config.py            # 所有配置参数（环境变量驱动）
  direction_scorer.py  # 9维度 BTC 方向评分（Binance API）
  hedge_formula.py     # 精确对冲数学公式
  decision.py          # 顺序门控交易决策层
  bot_state.py         # 状态持久化 + crash recovery
  polymarket_client.py # Polymarket CLOB API 客户端
  data_persistence.py  # SQLite 数据存储
  trading_engine.py    # 订单执行引擎
tests/                 # 单元测试
deploy/                # 部署脚本和配置
docs/                  # 文档
```

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env，填入 API_KEY

# 模拟运行（默认模式，不会下真实订单）
python bot_runner.py

# 运行测试
pip install pytest
pytest tests/
```

## 配置说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `TRADING_ENABLED` | `false` | ⚠️ 必须显式设为 true 才能真实交易 |
| `DRY_RUN` | `true` | 模拟模式（不提交订单） |
| `STRATEGY` | `imbalance` | 策略类型 |
| `SCORER_ENABLED` | `true` | 启用9维度评分器 |
| `BET_SIZE_USDC` | `3.0` | 每次主仓下注金额（USDC） |
| `DAILY_LOSS_LIMIT_USDC` | `20` | 每日最大亏损触发熔断 |
| `DAILY_TRADE_LIMIT` | `20` | 每日最大交易次数 |
| `CONSECUTIVE_LOSS_LIMIT` | `3` | 连续亏损上限 |
| `MAIN_PRICE_MIN` | `0.50` | 主仓价格窗口下限 |
| `MAIN_PRICE_MAX` | `0.65` | 主仓价格窗口上限 |
| `HEDGE_PRICE_MIN` | `0.05` | 对冲价格窗口下限 |
| `HEDGE_PRICE_MAX` | `0.15` | 对冲价格窗口上限 |
| `HEDGE_FIRST` | `true` | 先挂对冲单，确认后再下主仓 |
| `FEE_RATE` | `0.02` | Polymarket 手续费（2%） |
| `HARD_STOP_SEC` | `30` | 到期前N秒硬停不入场 |
| `POLLING_INTERVAL` | `60000` | 轮询间隔（毫秒） |

## 策略说明

### 执行顺序（重要）
1. 先挂对冲单（`HEDGE_FIRST=true`）
2. 等待对冲单成交确认
3. 再下主仓

### 9维度方向评分
从 Binance 公开 API 实时获取数据，计算加权评分：
- EMA交叉（权重 0.15）
- RSI趋势（0.10）
- VWAP位置（0.12）
- 成交量突增（0.13）
- **CVD累积量差（0.18，最重要）**
- 盘口深度比（0.15）
- 资金费率（0.07）
- 持仓量变化（0.05）
- 宏观动量（0.05）

### 对冲公式
```
最小对冲量: Q_h = (P_m × Q_m) / [(1 - P_h) × (1 - fee)]
可行条件:   (1-P_m)(1-P_h)(1-fee)² > P_m × P_h
主仓盈利:   π₁ = Q_m(1-P_m)(1-fee) - P_h × Q_h
```

## 风控

- **安全开关**：`TRADING_ENABLED=false`（默认）
- **每日熔断**：亏损超 `DAILY_LOSS_LIMIT_USDC` 自动停止
- **连续亏损保护**：连续亏损 N 次停止
- **Crash Recovery**：`bot_state.json` 原子写入，重启自动恢复
- **UTC日切**：每日0时自动重置计数器

## Docker 部署

```bash
docker build -t polymarket-bot .
docker run -d --name polymarket-bot \
  --restart unless-stopped \
  --env-file .env \
  polymarket-bot
```

详见 [deploy/DEPLOYMENT_GUIDE.md](deploy/DEPLOYMENT_GUIDE.md)