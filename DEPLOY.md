# 🚀 AWS 东京 VPS 部署指南

## 前置条件

- AWS EC2 实例（推荐 t3.small，东京区域 ap-northeast-1）
- Ubuntu 22.04 LTS
- Polymarket 账号 + API Key

---

## 第一步：准备 AWS EC2（东京节点）

1. 登录 [AWS Console](https://console.aws.amazon.com)
2. 选择区域：**ap-northeast-1（东京）**
3. 启动 EC2 实例：
   - AMI：Ubuntu Server 22.04 LTS
   - 实例类型：`t3.small`（2 vCPU, 2GB RAM，约 $15/月）
   - 存储：20GB SSD
   - 安全组：开放 22(SSH), 8501(Dashboard, 可选)
4. 下载 `.pem` 密钥文件

---

## 第二步：服务器初始化

```bash
# SSH 连接
ssh -i your-key.pem ubuntu@<你的EC2公网IP>

# 更新系统
sudo apt update && sudo apt upgrade -y

# 安装 Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker ubuntu
newgrp docker

# 安装 Docker Compose
sudo apt install docker-compose -y

# 克隆项目
git clone https://github.com/zh6025/polymarket-trading-bot.git
cd polymarket-trading-bot

# 配置环境变量
cp .env.example .env
nano .env  # 填入你的 API Key 等配置
```

---

## 第三步：启动机器人

```bash
# 模拟模式（推荐先测试）
docker-compose --profile simulate up -d

# 查看日志
docker-compose logs -f bot-simulate

# 确认无误后，切换到实盘模式
# 编辑 .env，将 DRY_RUN=false
docker-compose up -d bot
```

---

## 第四步：配置 GitHub Actions 自动部署

在 GitHub 仓库的 **Settings → Secrets and variables → Actions** 中添加以下 Secrets：

| Secret 名称 | 说明 | 示例 |
|---|---|---|
| `AWS_TOKYO_SSH_KEY` | SSH 私钥内容（.pem 文件内容） | `-----BEGIN RSA PRIVATE KEY-----...` |
| `AWS_TOKYO_HOST` | EC2 公网 IP 或域名 | `54.xxx.xxx.xxx` |
| `AWS_TOKYO_USER` | SSH 用户名 | `ubuntu` |

配置完成后，每次推送到 `main` 分支将自动：
1. 运行 dry-run 测试
2. 构建 Docker 镜像
3. SSH 部署到 AWS 东京 VPS

---

## 常用命令

```bash
# 查看机器人状态
docker-compose ps

# 查看实时日志
docker-compose logs -f bot

# 重启机器人
docker-compose restart bot

# 停止机器人
docker-compose stop bot

# 启动 Web 监控面板（端口 8501）
docker-compose --profile dashboard up -d

# 更新代码并重启
git pull origin main && docker-compose up -d --build bot
```

---

## 目录结构

```
polymarket-trading-bot/
├── .env                  # 环境变量配置（不提交到 Git）
├── .env.example          # 配置模板
├── Dockerfile            # Docker 构建文件
├── docker-compose.yml    # 容器编排配置
├── bot_continuous.py     # 主入口（实盘连续运行）
├── bot_simulate.py       # 模拟模式入口
├── bot_runner.py         # 单次运行入口
├── web_dashboard.py      # Web 监控面板
├── lib/                  # 核心库
│   ├── config.py         # 配置管理
│   ├── strategy.py       # 交易策略
│   ├── risk_manager.py   # 风控管理
│   └── polymarket_client.py  # API 客户端
├── logs/                 # 日志目录（自动创建）
└── .github/workflows/
    └── deploy.yml        # CI/CD 流水线
```

---

## 注意事项

- ⚠️ **务必先用 `DRY_RUN=true` 模拟模式测试，确认策略正常后再切换实盘**
- 🔒 `.env` 文件包含 API Key，已加入 `.gitignore`，切勿提交到 Git
- 📊 建议定期检查日志（`logs/` 目录）和机器人运行状态
- 💰 实盘模式下请合理设置 `DAILY_LOSS_LIMIT` 和 `MAX_POSITION_SIZE` 风控参数
