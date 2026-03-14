# 在 Railway 上部署 Polymarket Trading Bot

> **TL;DR**: 连接 GitHub 仓库，在 Railway 控制台填写环境变量，点击 Deploy —— 全程无需 SSH、无需服务器、无需命令行，VPN 也不影响操作。

> **推荐原因**: Railway 直接从 GitHub 部署，控制台完全基于浏览器，对 VPN 用户最友好。无需购买服务器，无需管理系统，$5 免费试用额度够跑几百小时。

---

## 目录 | Contents

1. [前提条件](#前提条件)
2. [第一步：注册 Railway 账号](#第一步注册-railway-账号)
3. [第二步：创建项目并连接 GitHub 仓库](#第二步创建项目并连接-github-仓库)
4. [第三步：添加环境变量](#第三步添加环境变量)
5. [第四步：挂载持久化存储卷](#第四步挂载持久化存储卷)
6. [第五步：触发部署](#第五步触发部署)
7. [第六步：切换实盘模式](#第六步切换实盘模式)
8. [日常运维](#日常运维)
9. [常见问题 FAQ](#常见问题-faq)

---

## 前提条件

- [GitHub](https://github.com) 账号（用于连接仓库）
- Polymarket 账号及 CLOB API 凭证（见下方"第三步"）
- 已 Fork 或 Clone 本仓库到你自己的 GitHub 账号下

> **如何 Fork 仓库**：  
> 打开 <https://github.com/zh6025/polymarket-trading-bot> → 右上角点击 **Fork** → 勾选你自己的账号 → 点击 **Create fork**

---

## 第一步：注册 Railway 账号

1. 打开 <https://railway.com>
2. 点击右上角 **"Login"** -> **"Login with GitHub"**（用 GitHub 账号直接授权，无需填写额外信息）
3. 授权后自动进入 Railway 控制台

> Railway 使用 GitHub OAuth 登录，全程无密码，对 VPN 用户最友好。

---

## 第二步：创建项目并连接 GitHub 仓库

1. 在 Railway 控制台首页点击 **"New Project"**（蓝色按钮）

2. 在弹出的菜单中选择 **"Deploy from GitHub repo"**

3. 如果是第一次使用，点击 **"Configure GitHub App"** 授权 Railway 访问你的仓库：
   - 选择 **"Only select repositories"**
   - 勾选你 Fork 后的 `polymarket-trading-bot` 仓库
   - 点击 **"Install & Authorize"**

4. 回到 Railway，从列表中找到并点击你的 `polymarket-trading-bot` 仓库

5. 弹出 **"Configure service"** 对话框：
   - Branch: 保持默认（`main`）
   - 点击 **"Add Variables"**（先不要急着 Deploy，下一步先填好环境变量）

   > 如果直接点了 Deploy 也没关系，后续可以随时添加变量然后重新部署。

---

## 第三步：添加环境变量

### 3.1 进入变量设置页

在项目页面，点击你的服务（默认名字通常是仓库名），然后点击顶部的 **"Variables"** 标签页。

### 3.2 添加所有必需变量

点击 **"New Variable"** 逐一添加以下变量（或使用 **"RAW Editor"** 批量粘贴）：

#### 方式一：使用 RAW Editor（推荐，一次性粘贴）

点击 **"RAW Editor"** 按钮，将以下内容**完整复制**后粘贴进去，然后修改标有 `← 修改这里` 的值：

```
TRADING_MODE=dry_run
PK=
POLYMARKET_FUNDER_ADDRESS=0xe95ce742AfC2977965998810f326192D1593c1E1
POLYMARKET_API_KEY=
POLYMARKET_API_SECRET=
POLYMARKET_API_PASSPHRASE=
CHAIN_ID=137
WEB3_POLYGON_RPC=https://polygon-rpc.com
MAX_TRADE_USDC=1.0
DAILY_MAX_LOSS_USDC=10.0
DIVERGENCE_THRESHOLD=0.10
USE_RELATIVE_DIVERGENCE=false
TREND_THRESHOLD_PCT=0.001
OPPORTUNITY_PRICE_MAX=0.20
TAKE_PROFIT_PRICE=0.40
FLATTEN_BEFORE_SETTLEMENT=true
DAILY_RESET_TZ_OFFSET_HOURS=8
LOOP_INTERVAL_SECS=1.0
LOG_LEVEL=INFO
DB_PATH=/data/trading_bot.db
```

> **DRY RUN（模拟模式）**: 以上配置无需填写任何密钥即可运行，机器人会读取真实盘口但不下单。
> 确认正常后再填入真实密钥并将 `TRADING_MODE` 改为 `live`。

#### 方式二：逐一添加关键变量

| 变量名 | 初始值 | 说明 |
|---|---|---|
| `TRADING_MODE` | `dry_run` | 模拟模式，**先保持此值** |
| `PK` | （留空） | 以太坊私钥，实盘时填写 |
| `POLYMARKET_FUNDER_ADDRESS` | `0xe95ce742AfC2977965998810f326192D1593c1E1` | 已预填，无需修改 |
| `POLYMARKET_API_KEY` | （留空） | 实盘时填写 |
| `POLYMARKET_API_SECRET` | （留空） | 实盘时填写 |
| `POLYMARKET_API_PASSPHRASE` | （留空） | 实盘时填写 |
| `CHAIN_ID` | `137` | Polygon 主网，无需修改 |
| `WEB3_POLYGON_RPC` | `https://polygon-rpc.com` | 公共 RPC，无需修改 |
| `MAX_TRADE_USDC` | `1.0` | 每笔最大金额（USDC） |
| `DAILY_MAX_LOSS_USDC` | `10.0` | 每日最大亏损上限 |
| `DB_PATH` | `/data/trading_bot.db` | 数据库路径，需与存储卷配合 |
| `LOG_LEVEL` | `INFO` | 日志级别 |

### 3.3 如何获取 Polymarket API 密钥

1. 打开 <https://polymarket.com> 并登录
2. 右上角头像 -> **Settings** -> **API Keys**
3. 点击 **"Generate Key"**，复制 `Key`、`Secret`、`Passphrase` 分别填入对应变量

---

## 第四步：挂载持久化存储卷

存储卷用于保存 SQLite 数据库（交易记录、PnL 数据）。没有存储卷，每次重启数据会丢失。

### 4.1 添加存储卷

1. 在 Railway 控制台，点击左侧 **"+ New"** 或在项目页面点击 **"Add Service"** -> **"Volume"**

   ```
   项目页面 -> Add Service -> Volume
   ```

2. 在弹出的 **"Add Volume"** 配置框中：
   - **Mount Path**: 填写 `/data`
   - 点击 **"Add"** 确认

3. Railway 会提示将此存储卷附加到你的服务，选择 `polymarket-trading-bot` 服务确认。

### 4.2 验证存储卷配置

添加完成后，在服务的 **"Settings"** -> **"Volumes"** 中可以看到：

```
/data  →  [volume-name]  100 GB
```

> 存储卷确保机器人重启后交易数据不丢失。

---

## 第五步：触发部署

### 5.1 首次部署

变量和存储卷配置完成后，Railway 通常会自动触发一次部署。如果没有自动触发：

1. 点击服务页面顶部的 **"Deployments"** 标签
2. 点击右上角 **"Deploy"** 按钮（或 **"Redeploy"**）

### 5.2 查看构建日志

部署开始后，点击正在进行的部署条目，可以看到实时构建日志：

```
Building Docker image...
Step 1/8 : FROM python:3.11-slim
Step 2/8 : RUN groupadd ...
...
Successfully built abc123
Deploying...
```

首次构建约需 **2-4 分钟**（下载 Python 依赖和 Docker 镜像层）。

### 5.3 查看运行日志

部署成功后，点击 **"Logs"** 标签可以看到机器人输出：

```json
{"timestamp": "2024-01-01T00:00:00Z", "level": "info", "event": "Bot starting in DRY RUN mode"}
{"timestamp": "2024-01-01T00:00:01Z", "level": "info", "event": "Discovering active BTC market..."}
{"timestamp": "2024-01-01T00:00:02Z", "level": "info", "event": "[DRY RUN] Watching orderbook..."}
```

看到 `[DRY RUN]` 字样说明机器人已在**模拟模式**正常运行。

---

## 第六步：切换实盘模式

在模拟模式运行无误后，切换到实盘：

### 6.1 填写真实密钥

1. 点击服务 -> **"Variables"** 标签
2. 找到以下变量，逐一点击修改：
   - `PK` = 你的以太坊私钥（`0x` 开头的 64 位十六进制）
   - `POLYMARKET_API_KEY` = 从 Polymarket Settings 获取
   - `POLYMARKET_API_SECRET` = 同上
   - `POLYMARKET_API_PASSPHRASE` = 同上

### 6.2 切换模式

将 `TRADING_MODE` 从 `dry_run` 改为 `live`。

### 6.3 重新部署

修改变量后，Railway 会**自动触发重新部署**。稍等 1-2 分钟后查看日志：

```json
{"event": "Bot starting in LIVE mode"}
{"event": "Placing order", "side": "UP", "usdc": 1.0}
```

---

## 日常运维

### 查看实时日志

Railway 控制台 -> 服务 -> **"Logs"** 标签，支持实时滚动和关键词搜索。

### 暂停/恢复机器人

- **暂停**: 服务页面右上角三点菜单 -> **"Pause Service"**（不会删除数据）
- **恢复**: 点击 **"Resume Service"** 或重新部署

### 更新代码

每次向 GitHub 仓库的 `main` 分支推送代码，Railway 会**自动检测并重新部署**（CI/CD 自动化）。

### 修改策略参数

直接在 **"Variables"** 标签页修改对应变量（如 `MAX_TRADE_USDC`、`DIVERGENCE_THRESHOLD`），保存后 Railway 自动重新部署。

### 删除项目

Railway 控制台 -> 项目设置 -> **"Delete Project"**（会删除所有数据，谨慎操作）。

---

## 常见问题 FAQ

### Q: Railway 有免费额度吗？

| 计划 | 免费额度 | 持久存储 |
|---|---|---|
| Trial（试用） | $5 一次性额度 | 支持（100 GB） |
| Hobby（$5/月） | 包含在月费内 | 支持（100 GB） |

> 按实际使用资源计费。1 vCPU / 512 MB 内存的 Python 进程约消耗 $2-3/月，加上存储约 $3-5/月，合计 Hobby 计划（$5/月）基本够用。

### Q: 为什么推荐 Railway 而不是 Vultr / DigitalOcean？

| 对比项 | Railway | Vultr | DigitalOcean |
|---|---|---|---|
| VPN 访问稳定性 | **最好**（GitHub OAuth） | 部分地区受限 | 部分地区受限 |
| 需要管理服务器 | **不需要** | 需要 | 需要 |
| 需要 SSH | **不需要** | 需要 | 需要 |
| 部署方式 | GitHub 连接 + 点击部署 | Startup Script | User Data |
| 代码更新 | **自动** | 手动 git pull | 手动 git pull |
| 最低月费 | $5（Hobby） | $6 | $6 |

### Q: 机器人崩溃了怎么办？

Railway 会**自动重启**（已在 `railway.toml` 中配置 `restartPolicyType = "ON_FAILURE"`）。在 **"Deployments"** 标签可以看到重启历史和崩溃日志。

### Q: 数据库文件在哪里？

数据库存储在 `/data/trading_bot.db`（对应 Railway Volume）。Railway 控制台目前不支持直接下载文件，如需导出数据，可在日志中查看 PnL 摘要，或在代码中添加导出功能。

### Q: 构建失败，日志显示 "Docker build failed" 怎么办？

常见原因：
1. 网络问题（pip install 超时）-> 点击 **"Redeploy"** 重试即可
2. `requirements.txt` 格式问题 -> 检查文件内容是否完整
3. Python 版本不兼容 -> 检查 Dockerfile 中的 `FROM python:3.11-slim`

### Q: Variables 页面改了值，但机器人没有更新？

Railway 修改变量后会自动触发重新部署。如果没有看到新的部署，手动点击 **"Deploy"** 按钮强制重新部署。

### Q: 如何查看交易记录和 PnL？

在 **"Logs"** 标签中搜索关键词：
- `pnl` — 查看损益记录
- `SELL` — 查看卖出记录
- `BUY` — 查看买入记录
- `[DRY RUN]` — 确认是否还在模拟模式

---

> 部署遇到问题？提交 [Issue](https://github.com/zh6025/polymarket-trading-bot/issues) 或查看 [README 主文档](../README.md)。
