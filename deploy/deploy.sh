#!/bin/bash
# deploy.sh — 完整部署脚本
set -e

REPO_DIR="${REPO_DIR:-/home/ubuntu/polymarket-trading-bot}"
IMAGE_NAME="polymarket-bot"

echo "=== 部署 Polymarket Trading Bot ==="

cd "$REPO_DIR"

# 拉取最新代码
git pull origin main

# 用 docker compose 构建并重启
docker compose --profile live build --no-cache
docker compose --profile live up -d --force-recreate

# 清理旧镜像
docker image prune -f

echo "=== 部署完成 ==="
docker compose --profile live ps
