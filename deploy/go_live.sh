#!/bin/bash
# deploy/go_live.sh — 一键上线脚本（小白版）
#
# 用法：
#   bash deploy/go_live.sh check       # 只检查环境，不动任何东西
#   bash deploy/go_live.sh dry         # 切换到 DRY_RUN 模式启动（推荐先跑 1 小时）
#   bash deploy/go_live.sh preflight   # 实盘前检查 DRY_RUN 日志 / 状态 / 参数
#   bash deploy/go_live.sh live        # 切换到实盘模式启动（小心！会真实下单）
#   bash deploy/go_live.sh stop        # 停止机器人
#   bash deploy/go_live.sh logs        # 实时看日志（Ctrl+C 退出）
#   bash deploy/go_live.sh status      # 查看 bot 状态 + 今日 PnL
#
# 这个脚本帮你做这些事：
# 1) 拉取最新代码（git pull）
# 2) 检查 .env 是否填了私钥 / funder
# 3) 检查链上授权是否完成（USDC + Conditional Token）
# 4) 用 docker compose 启动 / 停止机器人
# 5) 显示最近的日志和 PnL

set -e
cd "$(dirname "$0")/.."   # 切到项目根目录

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

ok() { echo -e "${GREEN}✅ $*${NC}"; }
warn() { echo -e "${YELLOW}⚠️  $*${NC}"; }
err() { echo -e "${RED}❌ $*${NC}"; }
info() { echo -e "ℹ️  $*"; }

ACTION="${1:-check}"

require_env_var() {
    local key="$1"
    if ! grep -qE "^${key}=.+" .env 2>/dev/null || grep -qE "^${key}=$" .env || grep -qE "^${key}=your_" .env; then
        err ".env 中缺少 ${key}（或者还是默认占位值），请先填好"
        return 1
    fi
    return 0
}

get_env_value() {
    local key="$1"
    grep -E "^${key}=" .env 2>/dev/null | tail -n 1 | cut -d= -f2-
}

cmd_check() {
    info "===== 1) 检查代码版本 ====="
    git fetch origin main >/dev/null 2>&1 || warn "拉取 origin 失败，可能没网"
    local local_hash; local_hash=$(git rev-parse HEAD 2>/dev/null || echo "unknown")
    local remote_hash; remote_hash=$(git rev-parse origin/main 2>/dev/null || echo "unknown")
    echo "本地版本: ${local_hash:0:8}"
    echo "远端版本: ${remote_hash:0:8}"
    if [ "$local_hash" != "$remote_hash" ]; then
        warn "本地代码不是最新，建议运行：git pull origin main"
    else
        ok "代码已经是最新"
    fi

    info "===== 2) 检查 .env ====="
    if [ ! -f .env ]; then
        err "找不到 .env 文件！请先复制 .env.example 为 .env 并填好"
        echo "   命令: cp .env.example .env && nano .env"
        exit 1
    fi
    local missing=0
    require_env_var POLY_PRIVATE_KEY || missing=1
    require_env_var POLY_FUNDER || missing=1
    if [ $missing -eq 1 ]; then
        err "请用 nano .env 把上面缺失的字段填好后再来"
        exit 1
    fi
    ok ".env 关键字段已填"

    info "===== 3) 检查 Docker ====="
    if ! command -v docker >/dev/null 2>&1; then
        err "docker 未安装"
        exit 1
    fi
    if ! docker compose version >/dev/null 2>&1; then
        err "docker compose（v2）未安装"
        exit 1
    fi
    ok "docker / docker compose 已就绪"

    info "===== 4) 检查时间同步（chrony）====="
    if command -v chronyc >/dev/null 2>&1; then
        chronyc tracking 2>/dev/null | grep -E "System time|Last offset|RMS offset" || warn "chronyc tracking 输出异常"
        ok "chrony 已安装"
    else
        warn "chrony 未安装（实盘前建议执行: sudo apt install -y chrony && sudo systemctl enable --now chrony）"
    fi

    info "===== 5) 检查链上授权 ====="
    if [ -f scripts/setup_allowance.py ]; then
        info "（如果还没授权，先在本机用钱包私钥跑 python3 scripts/setup_allowance.py）"
        info "（已授权可跳过此步）"
    fi

    info "===== 6) 检查容器状态 ====="
    docker compose ps 2>/dev/null || true

    info "===== 7) 当前 PnL ====="
    if [ -f data/bot_state.json ]; then
        python3 -c "
import json
try:
    s = json.load(open('data/bot_state.json'))
    print(f'  日期: {s.get(\"current_date\",\"-\")}')
    print(f'  今日 PnL: \${s.get(\"daily_pnl\",0):.4f}')
    print(f'  累计 PnL: \${s.get(\"total_pnl\",0):.4f}')
    print(f'  今日交易数: {s.get(\"daily_trade_count\",0)}')
    print(f'  连续亏损: {s.get(\"consecutive_losses\",0)}')
    print(f'  熔断器: {s.get(\"circuit_breaker\",False)}')
    print(f'  在场持仓: {len(s.get(\"open_positions\",[]))}')
    print(f'  历史持仓: {len(s.get(\"closed_positions\",[]))}')
except Exception as e:
    print('  （读取状态失败:', e, ')')
"
    else
        info "  暂无状态文件 (data/bot_state.json)，机器人还没跑过"
    fi

    ok "检查完成"
}

cmd_preflight() {
    info "===== 实盘前检查（DRY_RUN / 日志 / 状态 / 参数）====="
    local failed=0

    if [ ! -f .env ]; then
        err "找不到 .env 文件！请先复制 .env.example 为 .env 并填好"
        exit 1
    fi

    info "===== 1) 检查小额实盘参数 ====="
    local dry_run trading_enabled bet_size chain_id signature_type
    dry_run=$(get_env_value DRY_RUN)
    trading_enabled=$(get_env_value TRADING_ENABLED)
    bet_size=$(get_env_value BET_SIZE_USDC)
    chain_id=$(get_env_value POLY_CHAIN_ID)
    signature_type=$(get_env_value POLY_SIGNATURE_TYPE)

    if [ "$trading_enabled" = "true" ]; then
        ok "TRADING_ENABLED=true"
    else
        err "TRADING_ENABLED 应为 true，当前: ${trading_enabled:-未设置}"
        failed=1
    fi
    if [ "$dry_run" = "true" ]; then
        ok "DRY_RUN=true（实盘前应先完成模拟验证）"
    else
        err "实盘前请先保持 DRY_RUN=true 完成模拟验证，当前: ${dry_run:-未设置}"
        failed=1
    fi
    if [ "$bet_size" = "1" ] || [ "$bet_size" = "1.0" ]; then
        ok "BET_SIZE_USDC=${bet_size}"
    else
        err "首次实盘建议 BET_SIZE_USDC=1.0，当前: ${bet_size:-未设置}"
        failed=1
    fi
    if [ "$chain_id" = "137" ]; then
        ok "POLY_CHAIN_ID=137"
    else
        err "POLY_CHAIN_ID 应为 137，当前: ${chain_id:-未设置}"
        failed=1
    fi
    if [ "$signature_type" = "2" ]; then
        ok "POLY_SIGNATURE_TYPE=2"
    elif [ "$signature_type" = "1" ]; then
        warn "POLY_SIGNATURE_TYPE=1；仅 Email/MagicLink Proxy 账户应使用 1"
    else
        err "POLY_SIGNATURE_TYPE 应为 2（或确认为 Email/MagicLink 时用 1），当前: ${signature_type:-未设置}"
        failed=1
    fi

    info "===== 2) 检查实盘凭据存在 ====="
    require_env_var POLY_PRIVATE_KEY || failed=1
    require_env_var POLY_FUNDER || failed=1

    info "===== 3) 检查时间同步 ====="
    if command -v chronyc >/dev/null 2>&1; then
        chronyc tracking 2>/dev/null | grep -E "System time|Last offset|RMS offset" || warn "chronyc tracking 输出异常"
        ok "chrony 已安装"
    elif command -v timedatectl >/dev/null 2>&1; then
        if timedatectl show -p NTPSynchronized --value 2>/dev/null | grep -qi true; then
            ok "系统 NTP 同步已启用"
        else
            err "系统 NTP 未同步；5 分钟市场对时间敏感，请先安装/启用 chrony"
            failed=1
        fi
    else
        err "无法检查时间同步；请安装 chrony 并确认 offset 为毫秒级"
        failed=1
    fi

    info "===== 4) 检查最近 1 小时 DRY_RUN 日志 ====="
    local log_file="${TMPDIR:-/tmp}/polymarket_go_live_preflight.log"
    if docker compose logs --since=1h --tail=3000 bot >"$log_file" 2>/dev/null; then
        if grep -q "🔬 DRY-RUN:" "$log_file"; then
            ok "最近 1 小时日志中出现过 DRY-RUN 入场决策"
        else
            err "最近 1 小时日志中没有找到 '🔬 DRY-RUN:'；请继续 DRY_RUN 跑满并等到至少 1 次入场决策"
            failed=1
        fi
        if grep -E "ERROR|余额不足|授权不足|下单失败|未找到 .*token_id|未找到 token_id" "$log_file"; then
            err "最近 1 小时日志中发现错误/余额/授权/token_id 异常，请先处理"
            failed=1
        else
            ok "最近 1 小时日志未发现 ERROR / 余额不足 / 授权不足 / 下单失败 / token_id 异常"
        fi
    else
        err "无法读取 docker 日志；请确认 bot 容器已运行并已完成 DRY_RUN"
        failed=1
    fi

    info "===== 5) 检查熔断器状态 ====="
    if [ -f data/bot_state.json ]; then
        if python3 - <<'PY'
import json
import sys

with open('data/bot_state.json', encoding='utf-8') as f:
    state = json.load(f)
if state.get('circuit_breaker', False):
    print('circuit_breaker=True')
    sys.exit(1)
print('circuit_breaker=False')
PY
        then
            ok "circuit_breaker=False"
        else
            err "熔断器已触发，请先排查状态/PnL 后再实盘"
            failed=1
        fi
    else
        err "找不到 data/bot_state.json；请先完成 DRY_RUN 并确认状态文件已写入"
        failed=1
    fi

    info "===== 6) 检查链上余额/授权（只读）====="
    if [ -f scripts/setup_allowance.py ]; then
        if docker compose run --rm bot python3 scripts/setup_allowance.py --check; then
            ok "链上授权检查通过"
        else
            err "链上余额/授权检查未通过；请先执行: docker compose run --rm bot python3 scripts/setup_allowance.py"
            failed=1
        fi
    else
        warn "未找到 scripts/setup_allowance.py，跳过链上授权检查"
    fi

    if [ "$failed" -eq 0 ]; then
        ok "实盘前检查通过。下一步可执行: bash deploy/go_live.sh live"
    else
        err "实盘前检查未通过，请先处理上面的 ❌ 项"
        exit 1
    fi
}

cmd_dry() {
    info "===== 切换到 DRY_RUN 模式（不下真实单）====="
    cmd_check
    info "===== 修改 .env: DRY_RUN=true, TRADING_ENABLED=true ====="
    sed -i.bak -E 's/^DRY_RUN=.*/DRY_RUN=true/' .env
    sed -i.bak -E 's/^TRADING_ENABLED=.*/TRADING_ENABLED=true/' .env
    grep -E '^(DRY_RUN|TRADING_ENABLED|BET_SIZE_USDC)=' .env || true
    info "===== 启动 bot ====="
    docker compose up -d --build
    ok "已启动 (DRY_RUN). 用 'bash deploy/go_live.sh logs' 看日志"
}

cmd_live() {
    info "===== ⚠️ 切换到实盘模式 ⚠️ ====="
    cmd_preflight
    echo
    warn "实盘会真实下单消耗你的 USDC！"
    warn "建议把 BET_SIZE_USDC 设为 1（最小试单）"
    read -r -p "确认继续？输入 'YES I AM SURE' 才会启动: " ans
    if [ "$ans" != "YES I AM SURE" ]; then
        err "已取消"
        exit 1
    fi
    info "===== 修改 .env: DRY_RUN=false, TRADING_ENABLED=true ====="
    sed -i.bak -E 's/^DRY_RUN=.*/DRY_RUN=false/' .env
    sed -i.bak -E 's/^TRADING_ENABLED=.*/TRADING_ENABLED=true/' .env
    if ! grep -qE '^BET_SIZE_USDC=' .env; then
        echo "BET_SIZE_USDC=1" >> .env
    fi
    grep -E '^(DRY_RUN|TRADING_ENABLED|BET_SIZE_USDC)=' .env || true
    info "===== 启动 bot ====="
    docker compose up -d --build
    ok "已启动 (LIVE). 用 'bash deploy/go_live.sh logs' 持续监控"
    warn "如果发现异常，立刻执行: bash deploy/go_live.sh stop"
}

cmd_stop() {
    info "===== 停止 bot ====="
    docker compose down
    ok "已停止"
}

cmd_logs() {
    info "===== 实时日志（Ctrl+C 退出）====="
    docker compose logs -f --tail=100 bot
}

cmd_status() {
    cmd_check
}

case "$ACTION" in
    check)  cmd_check ;;
    dry)    cmd_dry ;;
    preflight) cmd_preflight ;;
    live)   cmd_live ;;
    stop)   cmd_stop ;;
    logs)   cmd_logs ;;
    status) cmd_status ;;
    *)      echo "用法: bash deploy/go_live.sh {check|dry|preflight|live|stop|logs|status}"; exit 1 ;;
esac
