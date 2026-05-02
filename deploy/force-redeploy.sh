#!/usr/bin/env bash
# force-redeploy.sh — 完全清掉旧机器人并按当前代码重建
#
# 使用场景：
#   日志里仍然出现仓库里已经删除的提示文案（例如 “只找到1个子市场，跳过本周期”），
#   说明容器跑的是旧镜像。运行此脚本可一次性把旧容器、旧镜像和悬挂资源全部清掉，
#   再用当前代码重新构建并启动。
#
# 用法：
#   cd /opt/polymarket-bot && sudo bash deploy/force-redeploy.sh
set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/polymarket-bot}"
SERVICE_NAME="polymarket-bot"

cd "$REPO_DIR"

echo "📥 拉取最新代码..."
git pull origin main

echo "🛑 停止 systemd 服务（若已安装）..."
if systemctl list-unit-files | grep -q "^${SERVICE_NAME}.service"; then
    sudo systemctl stop "${SERVICE_NAME}" || true
fi

echo "🧹 清理旧容器与编排资源..."
docker compose down --remove-orphans --rmi local || true
docker rm -f "${SERVICE_NAME}" 2>/dev/null || true

echo "🗑️  清理悬挂镜像..."
docker image prune -f

echo "🔨 无缓存重建镜像..."
docker compose build --no-cache bot

echo "🚀 启动新容器..."
docker compose up -d --force-recreate bot

echo "📊 状态："
docker compose ps

echo "✅ 重建完成。查看日志确认是否仍出现旧文案："
echo "   docker compose logs -f bot"
