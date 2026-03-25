#!/bin/bash
# setup-linode.sh — 服务器初始化脚本（Ubuntu 22.04）
set -e

echo "=== 初始化服务器 ==="

# 更新系统
apt-get update -y && apt-get upgrade -y

# 安装依赖
apt-get install -y python3 python3-pip python3-venv git curl

# 安装 Docker
curl -fsSL https://get.docker.com | sh
usermod -aG docker "$USER"

# 创建应用目录
mkdir -p /opt/polymarket-bot
cd /opt/polymarket-bot

echo "=== 服务器初始化完成 ==="
