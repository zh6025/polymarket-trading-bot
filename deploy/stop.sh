#!/bin/bash
# stop.sh — 停止/暂停机器人交易
#
# 用法:
#   bash deploy/stop.sh              # 停止所有容器（live + dryrun）
#   bash deploy/stop.sh live         # 只停止实盘容器
#   bash deploy/stop.sh dryrun       # 只停止 dry-run 容器
#   bash deploy/stop.sh pause        # 暂停交易（设 TRADING_ENABLED=false 并重启，容器保持运行）
#   bash deploy/stop.sh down         # 完全移除容器和网络
#
set -e

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$REPO_DIR"

MODE="${1:-all}"

case "$MODE" in
  live)
    echo "🛑 停止实盘容器..."
    docker compose --profile live stop
    echo "✅ 实盘容器已停止"
    docker compose --profile live ps
    ;;

  dryrun)
    echo "🛑 停止 dry-run 容器..."
    docker compose --profile dryrun stop
    echo "✅ dry-run 容器已停止"
    docker compose --profile dryrun ps
    ;;

  pause)
    echo "⏸️  暂停交易（TRADING_ENABLED=false）..."
    # 修改 .env 中的 TRADING_ENABLED
    if [ -f .env ]; then
      if grep -q "^TRADING_ENABLED=" .env; then
        sed -i 's/^TRADING_ENABLED=.*/TRADING_ENABLED=false/' .env
      else
        echo "TRADING_ENABLED=false" >> .env
      fi
      echo "✅ .env 已更新: TRADING_ENABLED=false"
    else
      echo "⚠️  未找到 .env 文件，请手动设置 TRADING_ENABLED=false"
    fi
    # 重启容器使配置生效
    if docker ps --format '{{.Names}}' | grep -qw polymarket-bot-dryrun; then
      docker compose --profile dryrun restart
      echo "✅ dry-run 容器已重启"
    fi
    if docker ps --format '{{.Names}}' | grep -qw polymarket-bot; then
      docker compose --profile live restart
      echo "✅ 实盘容器已重启"
    fi
    echo "⏸️  交易已暂停。恢复: 设 TRADING_ENABLED=true 后 restart"
    ;;

  down)
    echo "🗑️  完全移除所有容器和网络..."
    docker compose --profile live --profile dryrun down
    echo "✅ 所有容器和网络已移除"
    ;;

  all|"")
    echo "🛑 停止所有容器..."
    docker compose --profile live --profile dryrun stop
    echo "✅ 所有容器已停止"
    docker compose --profile live --profile dryrun ps
    ;;

  *)
    echo "用法: bash deploy/stop.sh [live|dryrun|pause|down|all]"
    echo ""
    echo "  live    — 停止实盘容器"
    echo "  dryrun  — 停止 dry-run 容器"
    echo "  pause   — 暂停交易（修改 .env 并重启，容器保持运行）"
    echo "  down    — 完全移除容器和网络"
    echo "  all     — 停止所有容器（默认）"
    exit 1
    ;;
esac
