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

## 使用 systemd

```bash
# 创建虚拟环境
python3 -m venv /opt/polymarket-bot/.venv
/opt/polymarket-bot/.venv/bin/pip install -r requirements.txt

# 安装服务
cp deploy/systemd/polymarket-bot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable polymarket-bot
systemctl start polymarket-bot
```

## 开启真实交易

⚠️ 在 `.env` 中确认以下设置：

```
TRADING_ENABLED=true   # 解除安全锁
DRY_RUN=false          # 关闭模拟模式
BET_SIZE_USDC=3.0      # 每次下注金额
DAILY_LOSS_LIMIT_USDC=20  # 每日最大亏损
```
