# 部署手册

## 快速部署（Docker Compose — 推荐）

```bash
# 1. 克隆仓库
git clone https://github.com/zh6025/polymarket-trading-bot.git ~/polymarket-trading-bot
cd ~/polymarket-trading-bot

# 2. 配置环境变量
cp .env.example .env
nano .env   # 填入 API_KEY, API_SECRET, API_PASSPHRASE

# 3. Dry-run 观察模式测试
docker compose --profile dryrun up -d
docker compose --profile dryrun logs -f

# 4. 确认正常后，切换实盘
docker compose --profile dryrun down
# 编辑 .env: TRADING_ENABLED=true, DRY_RUN=false
docker compose --profile live up -d
docker compose --profile live logs -f
```

## 使用 systemd（无 Docker）

```bash
# 创建虚拟环境
python3 -m venv ~/polymarket-trading-bot/.venv
~/polymarket-trading-bot/.venv/bin/pip install -r requirements.txt

# 安装服务
sudo cp deploy/systemd/polymarket-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable polymarket-bot
sudo systemctl start polymarket-bot

# 查看日志
sudo journalctl -u polymarket-bot -f
```

## 开启真实交易

⚠️ 在 `.env` 中确认以下设置：

```env
TRADING_ENABLED=true        # 解除安全锁
DRY_RUN=false               # 关闭模拟模式
BET_SIZE_USDC=1.0           # 首周建议小额
DAILY_LOSS_LIMIT_USDC=5.0   # 首周建议收紧
DAILY_TRADE_LIMIT=10        # 首周建议减少
CONSECUTIVE_LOSS_LIMIT=2    # 首周建议更敏感
```

详细的实盘准备流程请参考 `docs/LIVE_TRADING_CHECKLIST.md`。
