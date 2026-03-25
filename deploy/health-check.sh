#!/bin/bash
# health-check.sh — 健康检查
set -e

echo "=== Polymarket Bot 健康检查 ==="

# 检查容器是否运行
if docker ps | grep -q polymarket-bot; then
    echo "✅ 容器运行中"
else
    echo "❌ 容器未运行"
    exit 1
fi

# 检查最近日志
echo "--- 最近5行日志 ---"
docker logs --tail 5 polymarket-bot

echo "=== 健康检查完成 ==="
