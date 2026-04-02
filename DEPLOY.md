# 🚀 AWS 东京 EC2 部署指南

> 本指南适用于 V3 多窗口 BTC 5m 策略（`bot_runner.py`）

## 前置条件

- AWS EC2 实例（推荐 t3.small，东京区域 ap-northeast-1）
- Ubuntu 22.04 LTS
- Polymarket 账号 + CLOB API Key

---

## 第一步：准备 AWS EC2（东京节点）

1. 登录 [AWS Console](https://console.aws.amazon.com)
2. 选择区域：**ap-northeast-1（东京）**
3. 启动 EC2 实例：
   - AMI：Ubuntu Server 22.04 LTS
   - 实例类型：`t3.small`（2 vCPU, 2GB RAM，约 $15/月）
   - 存储：20GB gp3 SSD
   - 安全组：开放 22 (SSH)
4. 下载 `.pem` 密钥文件

---

## 第二步：服务器初始化

```bash
# SSH 连接
ssh -i your-key.pem ubuntu@<你的EC2公网IP>

# 方式 A：使用自动脚本
sudo bash deploy/setup-aws.sh

# 方式 B：手动初始化
sudo apt update && sudo apt upgrade -y
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker ubuntu
sudo apt install -y docker-compose-plugin
# 退出重连 SSH 使 docker 组生效
exit
```

```bash
# 重连后克隆项目
ssh -i your-key.pem ubuntu@<你的EC2公网IP>
git clone https://github.com/zh6025/polymarket-trading-bot.git
cd polymarket-trading-bot

# 配置环境变量
cp .env.example .env
nano .env  # 填入你的 Polymarket CLOB API 凭证
```

---

## 第三步：启动机器人（Dry-Run 观察模式）

```bash
# 先用 dry-run 模式测试，确保一切正常
docker compose --profile dryrun up -d

# 查看日志
docker compose --profile dryrun logs -f

# 确认日志中出现正常的 bias 计算和窗口决策后，停止 dry-run
docker compose --profile dryrun down
```

---

## 第四步：切换到实盘模式

```bash
# 编辑 .env
nano .env
```

按照 `docs/LIVE_TRADING_CHECKLIST.md` 的建议，首次实盘推荐配置：

```env
TRADING_ENABLED=true
DRY_RUN=false
BET_SIZE_USDC=1.0
DAILY_LOSS_LIMIT_USDC=5.0
DAILY_TRADE_LIMIT=10
CONSECUTIVE_LOSS_LIMIT=2
```

```bash
# 启动实盘机器人
docker compose --profile live up -d

# 查看实时日志
docker compose --profile live logs -f
```

---

## 第五步：配置 GitHub Actions 自动部署（可选）

在 GitHub 仓库的 **Settings → Secrets and variables → Actions** 中添加：

| Secret 名称 | 说明 | 示例 |
|---|---|---|
| `AWS_TOKYO_SSH_KEY` | SSH 私钥内容（.pem 文件内容） | `-----BEGIN RSA PRIVATE KEY-----...` |
| `AWS_TOKYO_HOST` | EC2 公网 IP 或域名 | `54.xxx.xxx.xxx` |
| `AWS_TOKYO_USER` | SSH 用户名 | `ubuntu` |

配置完成后，每次推送到 `main` 分支将自动：
1. 运行 76 个单元测试
2. 构建 Docker 镜像
3. SSH 部署到 AWS 东京 EC2

---

## 常用运维命令

```bash
# 查看机器人状态
docker compose --profile live ps

# 查看实时日志
docker compose --profile live logs -f

# 查看最近 50 行日志
docker compose --profile live logs --tail 50

# 重启机器人
docker compose --profile live restart

# 停止机器人（多种方式）
bash deploy/stop.sh              # 停止所有容器
bash deploy/stop.sh live         # 只停止实盘
bash deploy/stop.sh dryrun       # 只停止 dry-run
bash deploy/stop.sh pause        # 暂停交易（TRADING_ENABLED=false，容器保持运行）
bash deploy/stop.sh down         # 完全移除容器和网络

# 更新代码并重启
git pull origin main && docker compose --profile live up -d --build

# 健康检查
bash deploy/health-check.sh

# 查看持久状态
cat bot_state.json | python3 -m json.tool
```

---

## 目录结构（服务器上）

```
~/polymarket-trading-bot/
├── .env                    # 环境变量配置（不提交到 Git）
├── .env.example            # 配置模板
├── Dockerfile              # Docker 构建文件
├── docker-compose.yml      # 容器编排配置
├── bot_runner.py           # 主入口（多窗口策略循环）
├── bot_state.json          # 持久化状态（自动创建）
├── lib/                    # 核心库
│   ├── config.py           # 环境变量配置
│   ├── bot_state.py        # 全局状态持久化
│   ├── session_state.py    # 单市场会话跟踪
│   ├── market_data.py      # Binance + Polymarket 数据
│   ├── market_bias.py      # BTC 动量 → 方向偏差
│   ├── window_strategy.py  # 多窗口决策逻辑
│   ├── execution.py        # 订单执行层
│   └── polymarket_client.py # Polymarket CLOB API
├── logs/                   # 日志目录（自动创建）
├── tests/                  # 76 个单元测试
├── docs/                   # 策略和架构文档
│   ├── STRATEGY_V3.md
│   ├── ARCHITECTURE.md
│   └── LIVE_TRADING_CHECKLIST.md
├── deploy/                 # 部署脚本
│   ├── setup-aws.sh
│   ├── deploy.sh
│   └── health-check.sh
└── .github/workflows/
    └── deploy.yml          # CI/CD 流水线
```

---

## ⚠️ 注意事项

- **务必先用 dry-run 模式测试**，确认策略正常后再切换实盘
- `.env` 文件包含 API Key，已加入 `.gitignore`，切勿提交到 Git
- 建议定期检查日志和 `bot_state.json` 中的 PnL
- 实盘首周建议使用保守的风控参数（详见 `docs/LIVE_TRADING_CHECKLIST.md`）
- 紧急停止：设置 `TRADING_ENABLED=false` 并重启容器
