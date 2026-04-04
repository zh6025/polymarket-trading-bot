# 部署手册

## 快速部署（Docker）

```bash
git clone https://github.com/zh6025/polymarket-trading-bot.git /opt/polymarket-bot
cd /opt/polymarket-bot
cp .env.example .env

docker build -t polymarket-bot .
docker run -d --name polymarket-bot --restart unless-stopped \
  --env-file .env \
  -v /opt/polymarket-bot/logs:/app/logs \
  polymarket-bot

docker logs -f polymarket-bot
```

## 使用 docker-compose

```bash
docker-compose up -d bot
docker-compose logs -f bot
```

## 使用 systemd

```bash
python3 -m venv /opt/polymarket-bot/.venv
/opt/polymarket-bot/.venv/bin/pip install -r requirements.txt
cp deploy/systemd/polymarket-bot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable polymarket-bot
systemctl start polymarket-bot
```
