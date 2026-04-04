# 部署说明

仓库已清理为单一入口：`bot_continuous.py`。

## 本地运行

```bash
pip install -r requirements.txt
cp .env.example .env
python bot_continuous.py
```

## Docker

```bash
docker build -t polymarket-bot .
docker run -d --name polymarket-bot \
  --restart unless-stopped \
  --env-file .env \
  -v "$PWD/logs:/app/logs" \
  polymarket-bot
```

## docker-compose

```bash
docker-compose up -d bot
docker-compose logs -f bot
```
