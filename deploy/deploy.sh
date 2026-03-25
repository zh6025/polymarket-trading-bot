#!/bin/bash
# deploy.sh — 完整部署脚本
set -e

REPO_DIR="/opt/polymarket-bot"
IMAGE_NAME="polymarket-bot"

echo "=== 部署 Polymarket Trading Bot ==="

cd "$REPO_DIR"

# 拉取最新代码
git pull origin main

# 构建镜像
docker build -t "$IMAGE_NAME" .

# 停止旧容器
docker stop polymarket-bot 2>/dev/null || true
docker rm polymarket-bot 2>/dev/null || true

# 启动新容器
docker run -d \
  --name polymarket-bot \
  --restart unless-stopped \
  --env-file .env \
  -v "$REPO_DIR/logs:/app/logs" \
  "$IMAGE_NAME"

echo "=== 部署完成 ==="
docker ps | grep polymarket-bot
