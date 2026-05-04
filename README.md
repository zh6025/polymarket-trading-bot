# Polymarket BTC 5分钟末端狙击机器人

> 🚀 **不懂代码？想直接上线实盘？** 看这份小白版手册：[LIVE_TRADING_GUIDE.md](./LIVE_TRADING_GUIDE.md)
>
> 全程复制粘贴，约 40 分钟设置 + 1 小时模拟 + 24 小时小额验证。

自动交易 Polymarket BTC Up/Down 5分钟市场，采用末端狙击策略（Kelly公式 + 动量确认），在每个5分钟窗口的末端高胜率时刻入场。

## 架构

```
bot_sniper.py              # 主入口：主循环 + 周期协调
lib/
  config.py                # 所有配置参数（环境变量驱动）
  sniper_strategy.py       # 末端狙击策略核心（Kelly公式 + 动量确认）
  bot_state.py             # 状态持久化 + 风控 + crash recovery
  polymarket_client.py     # Polymarket CLOB API 客户端
  binance_feed.py          # Binance BTC 实时价格
  utils.py                 # 日志 + APIClient 工具
tests/                     # 单元测试
deploy/                    # 部署脚本和配置
```

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env，至少填入 POLY_PRIVATE_KEY 和 POLY_FUNDER（实盘必需）

# 模拟运行（默认模式，不会下真实订单）
python bot_sniper.py

# 运行测试
pip install pytest
pytest tests/
```

## 实盘交易上线流程

> ⚠️ 上线前**务必先用 `DRY_RUN=true` 跑通至少 1 小时**，确认决策日志正常。

1. **生成 Polymarket Proxy 钱包**
   登录 https://polymarket.com → 充值 USDC.e 到你的钱包 → 在账户设置里查看 funder 地址
2. **配置 `.env`**
   - `POLY_PRIVATE_KEY=` 钱包私钥
   - `POLY_FUNDER=0x...` Polymarket Proxy 地址
   - `POLY_CHAIN_ID=137`、`POLY_SIGNATURE_TYPE=2`
3. **链上一次性授权**（USDC + Conditional Token 对 Exchange 合约）
   ```bash
   python scripts/setup_allowance.py --check   # 检查授权状态
   python scripts/setup_allowance.py           # 实际发起授权交易
   ```
4. **服务器对时**（末端狙击对秒级精度敏感）
   ```bash
   sudo apt install -y chrony
   sudo systemctl enable --now chrony
   chronyc tracking   # 确认偏移 < 50ms
   ```
5. **小额验证**：先 `BET_SIZE_USDC=5`、`DRY_RUN=false` 跑 24 小时，观察 5–10 笔订单的成交、撤单、PnL 闭环
6. **可选：Telegram 告警** — 在 `.env` 配置 `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`
7. **状态持久化** — `STATE_FILE` 默认 `bot_state.json`，已在 `docker-compose.yml` 中挂卷

## 配置说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `TRADING_ENABLED` | `false` | ⚠️ 必须显式设为 true 才能真实交易 |
| `DRY_RUN` | `true` | 模拟模式（不提交订单） |
| `BET_SIZE_USDC` | `3.0` | 每次下注金额（USDC） |
| `DAILY_LOSS_LIMIT_USDC` | `20` | 每日最大亏损触发熔断 |
| `DAILY_TRADE_LIMIT` | `20` | 每日最大交易次数 |
| `CONSECUTIVE_LOSS_LIMIT` | `3` | 连续亏损上限 |
| `SNIPER_ENTRY_WINDOW_SEC` | `60` | 末端入场时间窗口（秒） |
| `HARD_STOP_SEC` | `30` | 到期前N秒硬停不入场 |
| `POLLING_INTERVAL` | `5000` | 轮询间隔（毫秒） |

## 策略说明

### 末端狙击策略（Kelly公式 + 动量确认）

在每个5分钟窗口末端 `SNIPER_ENTRY_WINDOW_SEC` 秒内入场：

1. **时机选择**：只在窗口末端（默认最后60秒）入场，胜率更高
2. **动量确认**：通过 Binance 实时价格确认 BTC 动量方向
3. **Kelly公式**：根据胜率和赔率动态计算最优仓位大小
4. **严格风控**：每日熔断 + 连续亏损保护 + Crash Recovery

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

或使用 Docker Compose：

```bash
docker compose up -d
```

详见 [deploy/DEPLOYMENT_GUIDE.md](deploy/DEPLOYMENT_GUIDE.md)
