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
git clone https://github.com/zh6025/polymarket-trading-bot.git /opt/polymarket-bot
cd /opt/polymarket-bot

# 配置环境变量
cp .env.example .env
nano .env  # 填入你的 API Key 等配置
```

---

## 第三步：启动机器人

```bash
# 模拟模式（推荐先测试，DRY_RUN=true 不下真实订单）
DRY_RUN=true docker-compose up -d bot

# 查看日志
docker-compose logs -f bot

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

# 重启机器人（仅复用已有镜像，不会拾取代码改动）
docker-compose down --remove-orphans && docker-compose up -d bot

# 停止机器人
docker-compose down

# 更新代码并重启（必须带 --build，否则会继续跑旧镜像里的旧代码）
git pull origin main && docker-compose down --remove-orphans && docker-compose up -d --build bot

# 强制重建镜像（怀疑跑的是旧代码时使用，例如日志里出现已经在仓库中删除的提示文案）
docker-compose build --no-cache bot && docker-compose up -d --force-recreate bot

# 一键彻底清掉旧机器人（停服务 + 删容器 + 删旧镜像 + 拉代码 + 无缓存重建 + 启动）
# 推荐：直接复制下面这一整段执行，不依赖仓库里是否已经存在 force-redeploy.sh，
# 适用于服务器代码过旧、脚本还没同步过来的情况。
cd /opt/polymarket-bot \
  && sudo git fetch origin main \
  && sudo git reset --hard origin/main \
  && (sudo systemctl stop polymarket-bot 2>/dev/null || true) \
  && sudo docker compose down --remove-orphans --rmi local || true \
  && sudo docker rm -f polymarket-bot 2>/dev/null || true \
  && sudo docker image prune -f \
  && sudo docker compose build --no-cache bot \
  && sudo docker compose up -d --force-recreate bot \
  && sudo docker compose ps

# 若服务器上已经有 deploy/force-redeploy.sh，可以改用脚本（效果等价）
sudo bash deploy/force-redeploy.sh
```

> 如果日志里仍然出现已从仓库删除的中文提示（例如 `只找到1个子市场，跳过本周期`），
> 说明容器跑的是旧镜像。优先使用上面的一键命令彻底清干净并重建；
> 当报 `deploy/force-redeploy.sh: No such file or directory` 时，
> 说明仓库里的脚本还没拉到本机——继续使用上面那一整段命令即可，不要单独执行
> `sudo bash deploy/force-redeploy.sh`。

### systemd 管理（服务器已安装服务时）

```bash
# 重启（服务会自动清理旧容器并重建镜像，相当于自动应用最新代码）
sudo systemctl restart polymarket-bot

# 查看状态
sudo systemctl status polymarket-bot --no-pager -l

# 查看日志
sudo journalctl -u polymarket-bot -n 50 --no-pager

# 重新加载并重启（含镜像重建）
sudo systemctl reload polymarket-bot

# 安装/更新 systemd 服务
sudo cp deploy/systemd/polymarket-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable polymarket-bot
```

---

## 目录结构

```
polymarket-trading-bot/
├── .env                  # 环境变量配置（不提交到 Git）
├── .env.example          # 配置模板
├── Dockerfile            # Docker 构建文件
├── docker-compose.yml    # 容器编排配置
├── bot_sniper.py         # 主入口：末端狙击机器人
├── lib/                  # 核心库
│   ├── config.py         # 配置管理
│   ├── sniper_strategy.py   # 末端狙击策略核心
│   ├── bot_state.py      # 状态持久化
│   ├── polymarket_client.py # API 客户端
│   ├── binance_feed.py   # Binance BTC 实时价格
│   └── utils.py          # 日志 + 工具
├── tests/                # 单元测试
├── deploy/               # 部署脚本和配置
│   ├── systemd/          # systemd 服务文件
│   └── deploy.sh         # 手动部署脚本
├── logs/                 # 日志目录（自动创建）
└── .github/workflows/
    └── deploy.yml        # CI/CD 流水线
```

---

## 故障排除

### Docker 容器名冲突

如果看到如下错误：

```
Error response from daemon: Conflict. The container name "/polymarket-bot" is already in use
```

解决方法：

```bash
# 手动清理旧容器
docker rm -f polymarket-bot
docker-compose up -d bot
```

systemd 服务已内置自动清理（`ExecStartPre=-docker compose down --remove-orphans`），
更新服务文件后重启即可：

```bash
sudo cp deploy/systemd/polymarket-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart polymarket-bot
```

---

## 注意事项

- ⚠️ **务必先用 `DRY_RUN=true` 模拟模式测试，确认策略正常后再切换实盘**
- 🔒 `.env` 文件包含 API Key，已加入 `.gitignore`，切勿提交到 Git
- 📊 建议定期检查日志（`logs/` 目录）和机器人运行状态
- 💰 实盘模式下请合理设置 `DAILY_LOSS_LIMIT` 和 `MAX_POSITION_SIZE` 风控参数
