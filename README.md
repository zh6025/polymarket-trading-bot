# Polymarket BTC Up/Down 5-Minute Trading Bot

An automated, production-ready trading bot that continuously discovers and
trades the recurring **"BTC Up or Down – 5 Minutes"** markets on
[Polymarket](https://polymarket.com) (CLOB), following a configurable
momentum-plus-orderbook strategy with strict risk controls.

> ⚠️ **Risk warning**: This bot places real orders with real money. Prediction
> markets are highly speculative. Only trade capital you can afford to lose.
> You are solely responsible for understanding the strategy, verifying the
> code, and complying with the laws of your jurisdiction.

---

## 🚀 Quick Start – Testing / Simulation (快速开始 – 测试/模拟)

### Step 1: 离线模拟（无需任何密钥）| Offline simulation – zero credentials needed

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the offline simulator – no API keys, no real money
python simulate.py                          # 3 cycles, mixed scenarios
python simulate.py --cycles 5               # run 5 market cycles
python simulate.py --scenario trending_up   # strong uptrend scenario
python simulate.py --scenario trending_down # strong downtrend scenario
python simulate.py --scenario volatile      # extreme price swings
python simulate.py --scenario ranging       # sideways market (bot mostly observes)
```

The simulator uses **synthetic BTC prices and synthetic order books** — it
exercises the complete strategy loop (state machine, risk limits, PnL
tracking) without touching any network or exchange.

### Step 2: 盘口干跑（读取真实盘口，不下单）| DRY RUN with live orderbook – no real orders

```bash
# 1. Copy the ready-made dry-run config (no real credentials needed)
cp .env.dry_run .env

# 2. Start the bot – reads live Polymarket orderbooks, places NO real orders
python runner.py

# Or with Docker:
docker compose up
```

All actions are logged as `[DRY RUN]`. Your wallet address is pre-configured.
No private key or API credentials are required for dry-run order-book reads.

### Step 3: 实盘交易 | Live trading – real money

Only when you are satisfied with dry-run behaviour:

```bash
cp .env.example .env
# Edit .env and set:
#   TRADING_MODE=live
#   PK=0xYOUR_PRIVATE_KEY
#   POLYMARKET_API_KEY / SECRET / PASSPHRASE
docker compose up -d
```

---

## Table of Contents

1. [Overview](#overview)
2. [VPS Deployment (推荐部署方式)](#vps-deployment)
3. [Setup](#setup)
4. [Configuration Variables](#configuration-variables)
5. [Running with Docker](#running-with-docker)
6. [How the Strategy Works](#how-the-strategy-works)
7. [Daily Loss Limit](#daily-loss-limit)
8. [DRY RUN Mode](#dry-run-mode)
9. [Offline Simulation (simulate.py)](#offline-simulation-simulatepy)
10. [Project Structure](#project-structure)
11. [Running Tests](#running-tests)

---

## Overview

Each **BTC Up or Down – 5 Minutes** market on Polymarket runs for exactly
5 minutes and resolves based on whether the Chainlink BTC/USD price at
market end is higher or lower than at market start.

The bot:

- **Auto-discovers** the currently active 5-minute BTC market and rolls to
  the next one when it expires.
- **Observes** the order book until the UP and DOWN ask prices diverge by at
  least 10% (configurable).
- **Checks the BTC trend** using 5-minute and 15-minute price returns from
  the Binance feed to decide direction.
- **Places a $1 USDC buy** in the trending direction.
- **Opportunistically buys** a second position if either side's ask drops
  below $0.20, and takes profit if that position rises above $0.40.
- **Manages exits**: sells on trend reversal, takes profit on opportunity
  position, and flattens or holds in the final 60 seconds.
- **Enforces risk limits**: $1 per trade, $10 daily max loss, max 2 entries
  per market, stops trading on repeated API failures.

---

## VPS Deployment

### 推荐的 VPS 供应商 | Recommended VPS Providers

Polymarket 的 CLOB 服务器位于美国东部，Binance WebSocket 延迟也越低越好。
建议选择**美国东部**或**欧洲**节点。最低配置要求很低 — 机器人是单个 Python 进程。

> Polymarket's CLOB servers are US-based. Lower latency = better price feed
> freshness. US-East or EU nodes are recommended. Minimum specs are tiny —
> the bot is a single Python process with a local SQLite file.

| 供应商 | 推荐地区 | 最低配置 | 月费（约） | 备注 |
|---|---|---|---|---|
| **[Vultr](https://www.vultr.com)** | New Jersey (美国东) | 1 vCPU / 1 GB RAM / 25 GB SSD | $6 | 按小时计费，随时可关 |
| **[DigitalOcean](https://www.digitalocean.com)** | New York 1/3 | 1 vCPU / 1 GB RAM / 25 GB SSD | $6 | 文档最完善，适合新手 |
| **[Hetzner](https://www.hetzner.com/cloud)** | Falkenstein / Helsinki | CX22: 2 vCPU / 4 GB RAM / 40 GB SSD | €4 | 欧洲最便宜，性价比最高 |
| **[Linode / Akamai](https://www.linode.com)** | Newark (美国东) | 1 vCPU / 1 GB RAM / 25 GB SSD | $5 | 稳定可靠 |
| **[AWS Lightsail](https://lightsail.aws.amazon.com)** | us-east-1 (弗吉尼亚) | 1 vCPU / 1 GB RAM / 40 GB SSD | $5 | 与 Polymarket 最近 |

> **推荐首选**: Vultr New Jersey — $6/月，延迟最低，支持"Startup Script"全自动部署。

### ⚡ Vultr 部署（最快方式，约 3 分钟完成）| Vultr Quick Deploy

> 📖 完整图文教程见 **[docs/vultr-deploy.md](docs/vultr-deploy.md)**

**三步完成部署，无需任何命令行操作：**

**① 注册 Vultr 账号**

前往 <https://my.vultr.com> 注册并添加付款方式（信用卡 / PayPal / 加密货币均可）。

**② 添加 Startup Script（一次性操作）**

登录后：左侧菜单 → **Startup Scripts** → **Add Startup Script**

- Name: `polymarket-bot-setup`
- Type: `Boot`
- Script: 打开 **[docs/vultr-deploy.md](docs/vultr-deploy.md#第二步添加-startup-script)** 文档，复制其中的代码框内容粘贴进去 →
  点击 **Save**

**③ 创建服务器**

左侧 **Instances** → **Deploy Instance**，配置如下：

| 设置 | 推荐值 |
|---|---|
| Type | Cloud Compute – Shared CPU |
| Location | **New Jersey (EWR)** |
| Image | **Ubuntu 22.04 LTS** |
| Plan | **$6/mo** (1 vCPU / 1 GB / 25 GB SSD) |
| Startup Script | **polymarket-bot-setup** ← 一定要选！|

点击 **Deploy Now** → 等待约 2–3 分钟 → SSH 登录：

```bash
ssh root@你的服务器IP
# 密码在 Vultr 控制台 → Instances → 你的服务器 → Overview
```

登录后机器人已在**模拟模式**运行。查看安装日志：

```bash
tail -f /var/log/polymarket-bot-setup.log
```

填入 API 密钥后切换实盘：

```bash
nano /opt/polymarket-bot/.env          # 填写 PK / CLOB_API_KEY / CLOB_SECRET / CLOB_PASSPHRASE
systemctl restart polymarket-bot       # 重启生效
journalctl -u polymarket-bot -f        # 查看实时日志
```

### 系统要求 | Minimum System Requirements

```
OS      : Ubuntu 22.04 LTS 或 24.04 LTS (64-bit)
CPU     : 1 vCPU（任意型号）
RAM     : 512 MB 最低，1 GB 推荐
Disk    : 10 GB（含 Docker 镜像）
Network : 任意出站网络（需访问 Polymarket、Binance、Polygon RPC）
```

### 一键部署 | One-Command Deploy (Ubuntu 22.04 / 24.04)

在全新 VPS 上以 root 身份运行以下命令，自动完成所有安装步骤：

```bash
# 1. SSH into your fresh VPS as root
ssh root@YOUR_VPS_IP

# 2. Download and run the bootstrap script
bash <(curl -fsSL https://raw.githubusercontent.com/zh6025/polymarket-trading-bot/main/deploy.sh)
```

脚本自动完成：
- ✅ 安装 Docker CE + Docker Compose
- ✅ 配置防火墙（仅开放 SSH 端口）
- ✅ 创建独立系统账户 `polybot`（最小权限）
- ✅ 克隆仓库到 `/opt/polymarket-bot`
- ✅ 复制 `.env.dry_run` 为初始配置（默认模拟模式，不下单）
- ✅ 注册 systemd 服务（开机自启动）

### 部署后的步骤 | After Deployment

```bash
# 1. 编辑配置文件（填入你的密钥）
nano /opt/polymarket-bot/.env

# 2. 开启实盘交易：将 TRADING_MODE=dry_run 改为 TRADING_MODE=live，然后重启
systemctl restart polymarket-bot

# 3. 查看实时日志
journalctl -u polymarket-bot -f

# 4. 查看交易数据
cd /opt/polymarket-bot && python view_trades.py

# 5. 停止机器人
systemctl stop polymarket-bot

# 6. 完全卸载
systemctl disable polymarket-bot
cd /opt/polymarket-bot && docker compose down -v
```

### 手动部署（不使用 deploy.sh）| Manual Setup

```bash
# 1. 安装 Docker（Ubuntu）
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker

# 2. 克隆仓库
git clone https://github.com/zh6025/polymarket-trading-bot.git
cd polymarket-trading-bot

# 3. 配置环境变量
cp .env.dry_run .env        # 模拟模式 – 无需密钥
# 或 cp .env.example .env  # 实盘模式 – 需填写密钥

# 4. 启动
docker compose up -d

# 5. 查看日志
docker compose logs -f
```

### 安全注意事项 | Security Notes

- 🔒 **永远不要** 将 `.env` 文件提交到 Git 仓库（已加入 `.gitignore`）
- 🔒 建议为 VPS 设置 SSH 密钥登录，禁用密码登录
- 🔒 `deploy.sh` 已配置防火墙只允许 SSH 入站
- 🔒 容器以非 root 用户 `botuser` 运行（见 `Dockerfile`）

---

## Setup

### Prerequisites

- Docker and Docker Compose installed on your VPS
- A Polymarket account with:
  - An Ethereum private key (`PK`) controlling your Polymarket wallet
  - CLOB API credentials (key, secret, passphrase) from Polymarket Settings
- (Optional) A Polygon RPC URL from [Alchemy](https://alchemy.com) or
  [Infura](https://infura.io) for on-chain Chainlink reads

### 1. Clone the repository

```bash
git clone https://github.com/zh6025/polymarket-trading-bot.git
cd polymarket-trading-bot
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and fill in your credentials and desired parameters.

### 3. (Optional) Run tests locally

```bash
pip install -r requirements.txt
pytest tests/ -v
```

---

## Configuration Variables

All configuration is via environment variables (loaded from `.env`).

| Variable | Default | Description |
|---|---|---|
| `TRADING_MODE` | `dry_run` | Set to `live` to enable real orders |
| `PK` | *(required for live)* | Ethereum private key (hex) |
| `POLYMARKET_FUNDER_ADDRESS` | `0xe95ce742…` | Your Polymarket wallet address (pre-filled) |
| `POLYMARKET_API_KEY` | *(required for live)* | CLOB API key |
| `POLYMARKET_API_SECRET` | *(required for live)* | CLOB API secret |
| `POLYMARKET_API_PASSPHRASE` | *(required for live)* | CLOB API passphrase |
| `CHAIN_ID` | `137` | Polygon mainnet chain ID |
| `WEB3_POLYGON_RPC` | `https://polygon-rpc.com` | Polygon RPC for Chainlink reads |
| `MAX_TRADE_USDC` | `1.0` | Maximum notional per order (USDC) |
| `DAILY_MAX_LOSS_USDC` | `10.0` | Daily loss limit before halt (USDC) |
| `DIVERGENCE_THRESHOLD` | `0.10` | Min ask price divergence to trigger entry |
| `USE_RELATIVE_DIVERGENCE` | `false` | Use relative (%) instead of absolute divergence |
| `TREND_THRESHOLD_PCT` | `0.001` | Minimum BTC return to register a trend (0.1%) |
| `OPPORTUNITY_PRICE_MAX` | `0.20` | Ask price below which opportunistic buy triggers |
| `TAKE_PROFIT_PRICE` | `0.40` | Mid price above which opportunity position is sold |
| `FLATTEN_BEFORE_SETTLEMENT` | `true` | Sell all in final 60s; false = hold if trend intact |
| `DAILY_RESET_TZ_OFFSET_HOURS` | `0` | UTC offset for daily counter reset (8 = CST) |
| `LOOP_INTERVAL_SECS` | `1.0` | Main loop polling interval (seconds) |
| `LOG_LEVEL` | `INFO` | Log verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `DB_PATH` | `/data/trading_bot.db` | SQLite database file path |

### About `POLYMARKET_FUNDER_ADDRESS`

Your Polymarket username is `0xe95ce742AfC2977965998810f326192D1593c1E1-1772245217002`.
The address part (`0xe95ce742AfC2977965998810f326192D1593c1E1`) is pre-filled as the
default value for `POLYMARKET_FUNDER_ADDRESS`.  This is the Polygon wallet address
that holds your USDC and is linked to your Polymarket CLOB API keys.  You do **not**
need to change it unless you use a different wallet.

---

## Running with Docker

### Start the bot

```bash
docker compose up -d
```

### View live logs

```bash
docker compose logs -f
```

### Stop the bot

```bash
docker compose down
```

### Check health

```bash
docker ps
```

The healthcheck verifies the SQLite database file exists (written on startup).

---

## How the Strategy Works

### Market Discovery

The bot queries the Polymarket Gamma API for events with a slug containing
`btc-updown-5m`.  It selects the event whose start time is in the past and
end time is in the future.  When a market expires it immediately re-runs
discovery to find the next one.

### State Machine

```
OBSERVE
  │  abs(up_ask - down_ask) >= 0.10  AND  BTC trend != NEUTRAL
  ▼
ENTERED  ($1 USDC order placed in trending direction)
  │  → ask < 0.20 AND > 60s to end   → OPPORTUNITY_BUY_DONE
  │  → trend reversal detected        → sell everything → EXITED
  │  → < 60s to end                   → FINAL_MINUTE
  ▼
OPPORTUNITY_BUY_DONE  (second $1 USDC order placed)
  │  → opportunity mid > 0.40         → take-profit sell
  │  → trend reversal                 → sell everything → EXITED
  │  → < 60s to end                   → FINAL_MINUTE
  ▼
FINAL_MINUTE
  │  FLATTEN_BEFORE_SETTLEMENT=true   → sell all
  │  FLATTEN_BEFORE_SETTLEMENT=false  → hold if trend consistent
  ▼
EXITED  (next market cycle begins)
```

### Trend Signal

- 5-minute return: `(current_price / price_300s_ago) - 1`
- 15-minute return: `(current_price / price_900s_ago) - 1`
- Both positive and above threshold → **UP**
- Both negative and below threshold → **DOWN**
- Otherwise → **NEUTRAL** (no entry)

### Chainlink as Resolution Oracle

Polymarket resolves BTC Up/Down markets using the
[Chainlink BTC/USD feed on Polygon](https://data.chain.link/polygon/mainnet/crypto-usd/btc-usd).
The bot reads this feed for reference.  Binance WebSocket provides low-latency
ticks for trend signals.

---

## Daily Loss Limit

When cumulative realised losses reach `DAILY_MAX_LOSS_USDC`:

1. The Risk Manager **halts** all new order placement.
2. An `ERROR`-level log message is written.
3. At midnight in the configured timezone the counter **resets** and trading
   **resumes automatically**.

To manually resume, restart the container:

```bash
docker compose restart trading-bot
```

---

## DRY RUN Mode

DRY RUN is the **default**.  In this mode:

- Order placement calls are **skipped**.
- The bot logs what *would* have been placed with the prefix `[DRY RUN]`.
- Order books are still fetched from the live Polymarket API.
- All strategy logic, risk checks, and PnL tracking run as normal.
- **No private key is required** — order books are public endpoints.

To enable **live trading**, set in `.env`:

```dotenv
TRADING_MODE=live
```

---

## Offline Simulation (`simulate.py`)

For testing with **zero network access and zero credentials**, use the
offline simulator:

```bash
python simulate.py [--cycles N] [--scenario SCENARIO] [--seed INT]
```

| Scenario | Description |
|---|---|
| `trending_up` | BTC rises steadily → expects UP entries, profit on flatten |
| `trending_down` | BTC falls steadily → expects DOWN entries |
| `ranging` | Sideways market – prices stay close, bot mostly observes |
| `volatile` | Sharp reversals – tests reversal-exit and opportunity-buy logic |
| `mixed` (default) | Cycles through trending_up → trending_down → ranging |

**What it does:**

1. Generates synthetic BTC prices with configurable trend and volatility
2. Builds realistic UP/DOWN order books from those prices
3. Runs the complete strategy state machine tick-by-tick
4. Prints every decision with timestamp, price, and PnL
5. Shows a summary table at the end

**Example output:**

```
════════════════════════════════════════════════════════════════
 Polymarket BTC Up/Down 5m – OFFLINE SIMULATION (模拟交易)
════════════════════════════════════════════════════════════════
 Cycles   : 3  |  Scenario : mixed  |  Seed : 42

[12:00:01] [Cycle 1]   Scenario: trending_up
[12:00:01]   OBSERVE   s=  0s  up_ask=0.510  down_ask=0.510  div=0.000
[12:00:01]   BUY (initial)  s=43s  UP  price=0.560  trend=UP  BTC=$83,000
[12:00:01]   SELL (final)   s=241s  UP  sell=0.771  pnl=+0.2110
[12:00:01] [Cycle 1 END]  realised_pnl = +0.2110 USDC

  SIMULATION SUMMARY
  Cycle    Scenario        PnL (USDC)
  1        trending_up        +0.2110
  2        trending_down      +0.2110
  3        ranging            +0.0000
  TOTAL                       +0.4220
```

---

## Project Structure

```
polymarket-trading-bot/
├── polymarket/            # Polymarket CLOB client
│   ├── auth.py            # Credential management + funder address
│   ├── client.py          # CLOB API wrapper (read-only if no PK)
│   ├── endpoints.py       # API URL constants (Gamma, CLOB, Binance, Chainlink)
│   ├── market_discovery.py# Auto-rolling market discovery via Gamma API
│   └── models.py          # Data models
├── feeds/                 # BTC price feeds
│   ├── base.py            # Abstract PriceFeed with rolling history
│   ├── binance.py         # Binance WebSocket + REST fallback
│   └── chainlink.py       # Chainlink on-chain / REST fallback
├── strategy/              # Strategy logic
│   ├── divergence.py      # Price divergence calculation
│   ├── signals.py         # 5m/15m trend signals
│   └── state_machine.py   # MarketSession state machine
├── risk/                  # Risk management
│   ├── limits.py          # RiskManager (daily loss, per-trade, circuit breaker)
│   └── pnl.py             # PnL tracker
├── storage/               # Persistence
│   └── db.py              # SQLite wrapper
├── tests/                 # Unit tests (76 tests)
├── runner.py              # Main entry point (live + dry-run)
├── simulate.py            # Offline simulation (zero credentials)
├── .env.example           # Full config template
├── .env.dry_run           # Ready-to-use dry-run config (no keys needed)
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

---

## Running Tests

```bash
pip install -r requirements.txt
pytest tests/ -v
```

---

## Disclaimer

This software is provided **as-is** for educational and research purposes.
The authors assume no liability for financial losses from its use.  Prediction
markets involve significant risk.  Always verify behaviour in DRY RUN mode
before enabling live trading.
