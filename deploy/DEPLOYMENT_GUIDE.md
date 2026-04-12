# 部署手册

## 快速部署（Docker）

```bash
# 1. 克隆仓库
git clone https://github.com/zh6025/polymarket-trading-bot.git /opt/polymarket-bot
cd /opt/polymarket-bot

# 2. 配置环境变量
cp deploy/.env.production .env
# 编辑 .env，填入 API_KEY 等真实值

# 3. 构建并启动
docker build -t polymarket-bot .
docker run -d --name polymarket-bot --restart unless-stopped \
  --env-file .env polymarket-bot

# 4. 查看日志
docker logs -f polymarket-bot
```

## 使用 docker-compose（生产推荐）

```bash
cd deploy
docker-compose -f docker-compose.prod.yml up -d
```

## 使用 systemd（Docker Compose 方式）

```bash
# 确保 Docker 和 Docker Compose 已安装
# 项目已克隆到 /opt/polymarket-bot

# 安装服务
sudo cp deploy/systemd/polymarket-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable polymarket-bot
sudo systemctl start polymarket-bot

# 查看状态
sudo systemctl status polymarket-bot --no-pager -l

# 查看日志
sudo journalctl -u polymarket-bot -n 50 --no-pager
```

> **注意**：systemd 服务会在启动前自动清理旧容器（`ExecStartPre=-docker compose down --remove-orphans`），
> 避免出现容器名 `/polymarket-bot` 冲突的问题。

## 开启真实交易

⚠️ 在 `.env` 中确认以下设置：

```
TRADING_ENABLED=true   # 解除安全锁
DRY_RUN=false          # 关闭模拟模式
BET_SIZE_USDC=3.0      # 每次下注金额
DAILY_LOSS_LIMIT_USDC=20  # 每日最大亏损
```
