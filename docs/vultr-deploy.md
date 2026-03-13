# 在 Vultr 上部署 Polymarket Trading Bot

> **TL;DR**: 在 Vultr 创建一台 $6/月的服务器，在 "Startup Script" 字段粘贴下方 **[第二步](#第二步添加-startup-script)** 中的脚本，服务器启动后机器人自动安装好。

---

## 目录 | Contents

1. [前提条件](#前提条件)
2. [第一步：注册 Vultr 账号](#第一步注册-vultr-账号)
3. [第二步：添加 Startup Script](#第二步添加-startup-script)
4. [第三步：创建服务器](#第三步创建服务器)
5. [第四步：SSH 登录并填写密钥](#第四步ssh-登录并填写密钥)
6. [第五步：切换实盘模式](#第五步切换实盘模式)
7. [日常运维命令](#日常运维命令)
8. [常见问题 FAQ](#常见问题-faq)

---

## 前提条件

- Vultr 账号（[免费注册](https://www.vultr.com/?ref=polymarket-bot)，支持信用卡 / PayPal / 加密货币）
- Polymarket 账号及 CLOB API 凭证（见下方"第四步"）
- 一个 SSH 客户端（Windows 用 [PuTTY](https://putty.org/) 或 PowerShell；Mac/Linux 自带 `ssh`）

---

## 第一步：注册 Vultr 账号

1. 打开 <https://my.vultr.com>
2. 点击 **"Create Account"** → 填写邮箱 + 密码 → 验证邮箱
3. 添加付款方式（信用卡 / PayPal / 比特币均可）

---

## 第二步：添加 Startup Script

Vultr 的 **Startup Script** 功能可以在服务器**第一次启动时**自动执行一段 Shell 脚本，帮你完成全部安装工作，无需任何手动操作。

> ⚠️ **新版 Vultr 控制台导航变化**  
> Startup Scripts 已从顶层侧边栏移至 **产品 → 管弦乐 → 脚本**（见下图路径）。

1. 登录后，在左侧菜单点击 **"产品"** → 展开后点击最底部的 **"管弦乐"** → 再点击 **"脚本"**

   ```
   左侧导航栏 → 产品 → 管弦乐（Orchestration）→ 脚本（Scripts）
   ```

   > 英文界面路径：**Products → Orchestration → Scripts**

2. 点击右上角 **"Add Startup Script"**

3. 填写表单：
   - **Script Name**: `polymarket-bot-setup`
   - **Type**: `Boot`
   - **Script**: 将下方代码框中的**全部内容**复制后粘贴进去（点击右上角复制按钮，或全选后 Ctrl+C）：

   ```bash
   #!/usr/bin/env bash
   # Polymarket Trading Bot – Vultr Startup Script
   set -euo pipefail

   LOG_FILE="/var/log/polymarket-bot-setup.log"
   exec > >(tee -a "${LOG_FILE}") 2>&1

   REPO_URL="https://github.com/zh6025/polymarket-trading-bot.git"
   INSTALL_DIR="/opt/polymarket-bot"
   SERVICE_NAME="polymarket-bot"
   BOT_USER="polybot"

   echo "============================================================"
   echo " Polymarket Trading Bot – Vultr Startup Script"
   echo " Started at: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
   echo " Log file  : ${LOG_FILE}"
   echo "============================================================"

   echo "[1/8] Waiting for network connectivity..."
   for i in $(seq 1 30); do
       if curl -fsSL --max-time 5 https://github.com > /dev/null 2>&1; then
           echo "      Network ready after ${i}s"; break
       fi
       sleep 1
   done

   echo "[2/8] Updating system packages..."
   export DEBIAN_FRONTEND=noninteractive
   apt-get update -qq
   apt-get upgrade -y -qq -o Dpkg::Options::="--force-confdef" \
                           -o Dpkg::Options::="--force-confold"
   apt-get install -y -qq git curl ufw ca-certificates gnupg lsb-release

   echo "[3/8] Installing Docker CE..."
   if command -v docker &>/dev/null; then
       echo "      Docker already installed: $(docker --version)"
   else
       install -m 0755 -d /etc/apt/keyrings
       DOCKER_GPG_URL="https://download.docker.com/linux/ubuntu/gpg"
       DOCKER_GPG_FILE="/etc/apt/keyrings/docker.gpg"
       EXPECTED_FINGERPRINT="9DC8 5822 9FC7 DD38 854A  E2D8 8D81 803C 0EBF CD88"
       curl -fsSL "${DOCKER_GPG_URL}" | gpg --dearmor -o "${DOCKER_GPG_FILE}"
       chmod a+r "${DOCKER_GPG_FILE}"
       ACTUAL_FINGERPRINT=$(gpg --no-default-keyring --keyring "${DOCKER_GPG_FILE}" \
           --fingerprint 2>/dev/null | grep -A1 "pub" | tail -1 | tr -d ' ')
       EXPECTED_STRIPPED=$(echo "${EXPECTED_FINGERPRINT}" | tr -d ' ')
       if [[ "${ACTUAL_FINGERPRINT}" != "${EXPECTED_STRIPPED}" ]]; then
           rm -f "${DOCKER_GPG_FILE}"
           echo "ERROR: Docker GPG fingerprint mismatch – aborting."; exit 1
       fi
       echo "      Docker GPG key fingerprint verified"
       echo "deb [arch=$(dpkg --print-architecture) signed-by=${DOCKER_GPG_FILE}] \
   https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
           > /etc/apt/sources.list.d/docker.list
       apt-get update -qq
       apt-get install -y -qq docker-ce docker-ce-cli containerd.io \
           docker-buildx-plugin docker-compose-plugin
       systemctl enable --now docker
       echo "      Docker installed: $(docker --version)"
   fi

   echo "[4/8] Configuring firewall..."
   ufw --force reset
   ufw default deny incoming
   ufw default allow outgoing
   ufw allow ssh
   ufw --force enable
   echo "      Firewall enabled: SSH only"

   echo "[5/8] Creating system user '${BOT_USER}'..."
   if ! id "${BOT_USER}" &>/dev/null; then
       useradd --system --shell /bin/false --home "${INSTALL_DIR}" "${BOT_USER}"
       usermod -aG docker "${BOT_USER}"
       echo "      User '${BOT_USER}' created"
   else
       echo "      User '${BOT_USER}' already exists"
   fi

   echo "[6/8] Cloning repository..."
   if [[ -d "${INSTALL_DIR}/.git" ]]; then
       git -C "${INSTALL_DIR}" pull --ff-only
   else
       git clone --depth 1 "${REPO_URL}" "${INSTALL_DIR}"
   fi
   chown -R "${BOT_USER}:${BOT_USER}" "${INSTALL_DIR}"

   echo "[7/8] Setting up .env..."
   ENV_FILE="${INSTALL_DIR}/.env"
   if [[ ! -f "${ENV_FILE}" ]]; then
       cp "${INSTALL_DIR}/.env.dry_run" "${ENV_FILE}"
       chown "${BOT_USER}:${BOT_USER}" "${ENV_FILE}"
       chmod 600 "${ENV_FILE}"
       echo "      .env created (DRY RUN mode – no real orders)"
   fi

   echo "[8/8] Installing systemd service '${SERVICE_NAME}'..."
   cat > "/etc/systemd/system/${SERVICE_NAME}.service" << 'UNIT'
   [Unit]
   Description=Polymarket BTC Up/Down 5-Minute Trading Bot
   After=network-online.target docker.service
   Wants=network-online.target
   Requires=docker.service

   [Service]
   Type=simple
   User=polybot
   Group=polybot
   WorkingDirectory=/opt/polymarket-bot
   ExecStartPre=/usr/bin/docker compose pull --quiet || true
   ExecStart=/usr/bin/docker compose up --build
   ExecStop=/usr/bin/docker compose down
   Restart=on-failure
   RestartSec=30
   TimeoutStartSec=120
   TimeoutStopSec=30
   NoNewPrivileges=yes
   PrivateTmp=yes

   [Install]
   WantedBy=multi-user.target
   UNIT

   systemctl daemon-reload
   systemctl enable "${SERVICE_NAME}"
   systemctl start "${SERVICE_NAME}" || true

   echo ""
   echo "============================================================"
   echo " Setup complete!  部署完成！"
   echo " Finished at: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
   echo " Log file: ${LOG_FILE}"
   echo "============================================================"
   echo " Next: ssh root@YOUR_IP  →  nano ${INSTALL_DIR}/.env"
   ```

4. 点击 **"Save"**

---

## 第三步：创建服务器

1. 在左侧菜单点击 **"产品"** → **"计算"** → 右上角点击 **"Deploy Instance"**（蓝色部署按钮）

   ```
   左侧导航栏 → 产品 → 计算（Compute）→ 实例（Instances）→ Deploy Instance
   ```

2. 按以下选项配置：

   | 设置项 | 推荐选择 | 说明 |
   |---|---|---|
   | **Choose Type** | Cloud Compute – Shared CPU | 最经济，完全够用 |
   | **Location** | New Jersey (EWR) | 距 Polymarket CLOB 服务器最近 |
   | **Image** | Ubuntu 22.04 LTS x64 | 推荐，经过充分测试 |
   | **Plan** | Regular Performance – $6/mo | 1 vCPU / 1 GB RAM / 25 GB SSD |
   | **Additional Features** | ✅ Enable IPv6（可选） | 无额外费用 |
   | **Startup Script** | `polymarket-bot-setup` | ← **一定要选这个！** |
   | **Server Hostname** | `polymarket-bot` | 随意，便于识别 |

3. 点击底部 **"Deploy Now"**

4. 等待约 **2–3 分钟**，状态从 `Installing` 变为 `Running`

---

## 第四步：SSH 登录并填写密钥

### 获取服务器 IP 和 root 密码

在 **产品 → 计算 → 实例** 列表中点击你的服务器 → **"Overview"** 标签页  
可以看到：
- **IP Address**（公网 IP，如 `45.76.123.45`）
- **Password**（root 密码，点击眼睛图标查看）

### SSH 登录

```bash
# Mac / Linux / Windows PowerShell
ssh root@45.76.123.45
# 输入密码后回车
```

### 查看安装日志（可选，确认安装成功）

```bash
tail -f /var/log/polymarket-bot-setup.log
```

看到以下内容说明安装完成：

```
============================================================
 Setup complete!  部署完成！
============================================================
```

### 填写 API 密钥

```bash
nano /opt/polymarket-bot/.env
```

需要填写的字段（从 [Polymarket 设置页](https://polymarket.com/settings) 获取）：

```dotenv
# ── 以太坊私钥（控制你的 Polymarket 钱包）──────────────────────
PK=0x你的私钥（64位十六进制，不含0x前缀也可以）

# ── Polymarket CLOB API 凭证 ───────────────────────────────────
CLOB_API_KEY=从Polymarket Settings → API Keys 获取
CLOB_SECRET=同上
CLOB_PASSPHRASE=同上

# ── 可选：Polygon RPC（提高链上数据精度）─────────────────────
# POLYGON_RPC_URL=https://polygon-mainnet.g.alchemy.com/v2/你的KEY
```

> 保存并退出 nano：按 `Ctrl+O` → `Enter` → `Ctrl+X`

---

## 第五步：切换实盘模式

默认配置是 **DRY RUN（模拟模式）**，不会下任何真实订单。确认一切正常后，切换实盘：

```bash
# 编辑 .env
sed -i 's/TRADING_MODE=dry_run/TRADING_MODE=live/' /opt/polymarket-bot/.env

# 重启机器人
systemctl restart polymarket-bot

# 确认已在实盘模式
grep TRADING_MODE /opt/polymarket-bot/.env
# 应输出: TRADING_MODE=live
```

---

## 日常运维命令

```bash
# ── 查看实时日志 ───────────────────────────────────────────────
journalctl -u polymarket-bot -f
# 或
cd /opt/polymarket-bot && docker compose logs -f

# ── 查看交易数据（订单、成交、PnL）────────────────────────────
cd /opt/polymarket-bot && python view_trades.py

# ── 重启机器人 ─────────────────────────────────────────────────
systemctl restart polymarket-bot

# ── 停止机器人 ─────────────────────────────────────────────────
systemctl stop polymarket-bot

# ── 查看运行状态 ───────────────────────────────────────────────
systemctl status polymarket-bot

# ── 更新代码（拉取最新版本）────────────────────────────────────
cd /opt/polymarket-bot
git pull --ff-only
docker compose build --no-cache
systemctl restart polymarket-bot

# ── 完全卸载 ───────────────────────────────────────────────────
systemctl disable --now polymarket-bot
cd /opt/polymarket-bot && docker compose down -v
```

---

## 常见问题 FAQ

### Q: Startup Script 运行完了吗？怎么确认？

```bash
# 查看完整安装日志
cat /var/log/polymarket-bot-setup.log

# 检查服务状态
systemctl status polymarket-bot
```

### Q: 机器人启动失败怎么办？

```bash
# 查看详细错误
journalctl -u polymarket-bot -n 100 --no-pager
docker compose -f /opt/polymarket-bot/docker-compose.yml logs
```

常见原因：
- `.env` 中的 `PK` / `CLOB_API_KEY` 填写有误 → 重新检查
- Docker 镜像还在下载中 → 等待 1 分钟后重试

### Q: 如何查看我的 Polymarket API 密钥？

1. 打开 <https://polymarket.com> 并登录
2. 右上角头像 → **Settings** → **API Keys**
3. 点击 **"Generate Key"**，复制 `Key`、`Secret`、`Passphrase` 填入 `.env`

### Q: 每月花费是多少？

| 项目 | 费用 |
|---|---|
| Vultr New Jersey – 1 vCPU / 1 GB | $6/月 |
| 交易手续费（Polymarket CLOB Maker） | ~0% |
| 每次交易资金（USDC） | $1（由 `TRADE_SIZE_USDC=1` 控制） |

> Vultr 按小时计费。不需要时随时关机，按实际使用小时数收费。

### Q: 如何加固服务器安全？

```bash
# 禁用 root 密码登录，改用 SSH 密钥
# 1. 在本地生成 SSH 密钥（如果还没有）
ssh-keygen -t ed25519 -C "polymarket-bot"

# 2. 将公钥复制到服务器
ssh-copy-id root@YOUR_SERVER_IP

# 3. 禁用密码登录
sed -i 's/#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl restart sshd
```

---

> 部署遇到问题？查看 [README 主文档](../README.md) 或提交 [Issue](https://github.com/zh6025/polymarket-trading-bot/issues)。
