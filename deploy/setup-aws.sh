#!/bin/bash
# setup-aws.sh — AWS EC2 (Ubuntu 22.04) 初始化脚本
# 适用于 ap-northeast-1 (东京) t3.small 实例
set -e

echo "=== 初始化 AWS EC2 服务器 ==="

# 更新系统
apt-get update -y && apt-get upgrade -y

# 安装依赖
apt-get install -y python3 python3-pip python3-venv git curl

# 安装 Docker
curl -fsSL https://get.docker.com | sh
usermod -aG docker ubuntu

# 安装 Docker Compose (V2 plugin)
apt-get install -y docker-compose-plugin

# 创建应用目录
mkdir -p /home/ubuntu/polymarket-trading-bot

# 设置时区为 UTC（交易计时用）
timedatectl set-timezone UTC

echo "=== 服务器初始化完成 ==="
echo "接下来："
echo "  1. 退出 SSH 并重新连接（使 docker 组生效）"
echo "  2. cd ~/polymarket-trading-bot"
echo "  3. git clone https://github.com/zh6025/polymarket-trading-bot.git ."
echo "  4. cp .env.example .env && nano .env"
echo "  5. docker compose --profile dryrun up -d"
