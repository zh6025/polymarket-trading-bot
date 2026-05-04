# 🚀 Polymarket Bot 实盘上线 — 零代码基础操作手册

> **这份文档是写给"完全不懂代码"的你的。** 每一步都告诉你：
> 1. 在哪里执行
> 2. 复制哪一行命令
> 3. 看到什么算成功
>
> 全程预计：**40 分钟设置 + 1 小时模拟 + 24 小时小额验证 = 共 ~26 小时**
>
> 你只需要做的事：**充值钱包、填私钥、对照本文档复制粘贴命令**。
> 任何看不懂的步骤可以截图发给 AI 助手问。

---

## 📋 准备清单（开始前请确认）

- [ ] 一个 Polymarket 账户（已注册并完成 KYC）
- [ ] Polymarket 钱包里有 **至少 50 USDC.e**（首次小额验证需要）
- [ ] Polymarket 钱包里有 **至少 5 MATIC**（用于支付链上授权 gas，约 $0.5）
- [ ] 一台已经部署过 bot 的服务器（你之前用 GitHub Actions 部署过 AWS Tokyo VPS 就是它）
- [ ] 服务器的 SSH 登录方式（用 PuTTY、Termius、或者命令行 `ssh` 都行）

如果你只有 Polymarket 余额、没有 USDC.e/MATIC 在自己钱包，先看 **附录 A：怎么把钱从 Polymarket 提到自己钱包**。

---

## 第 0 步：理解三个关键概念（30 秒）

| 概念 | 说明 |
|------|------|
| **私钥 (POLY_PRIVATE_KEY)** | 你 Polymarket 钱包的"开锁密码"。**只能存在你自己的服务器 .env 文件里，永远不要发给任何人，不要传 GitHub。** |
| **Funder 地址 (POLY_FUNDER)** | 你 Polymarket 账户对应的 Proxy 钱包地址。在 polymarket.com 登录后，账户页可以看到。 |
| **DRY_RUN** | =true 表示模拟模式（只决策、不真实下单）。第一次必须用 DRY_RUN=true 跑 1 小时。 |

---

## 第 1 步：导出私钥并记下 Funder 地址（5 分钟）

### 1.1 导出 Polymarket 私钥
1. 打开 https://polymarket.com 并登录
2. 右上角头像 → **Settings → Export Private Key**
3. 输入登录密码，会显示一串以 `0x` 开头的 64 位字符（例如 `0xabc123...def`）
4. **复制下来，临时保存到一个安全地方**（比如 1Password、密码管理器；不要存微信/QQ）

### 1.2 复制 Funder 地址
1. 同一个 Settings 页面，找到 "Deposit Address" 或 "Wallet Address"
2. **复制下来**（也是 `0x` 开头的 42 位字符）

> ⚠️ **私钥泄露 = 钱被全部偷走**。这一串只发给你自己的服务器，任何人（包括我、客服、推特上的"工作人员"）都不要给。

---

## 第 2 步：登录服务器（2 分钟）

打开你的终端（Mac: 终端 / Windows: PowerShell 或 PuTTY），执行：

```bash
ssh ubuntu@你的服务器IP地址
```

> 服务器 IP 就是你部署到 AWS Tokyo VPS 时用的那个地址。如果忘了，去 GitHub 仓库 Settings → Secrets → Actions 里看 `AWS_TOKYO_HOST` 这个变量。

进入服务器后，切到项目目录：

```bash
cd /opt/polymarket-bot
```

---

## 第 3 步：拉取最新代码（1 分钟）

```bash
git pull origin main
```

看到 `Already up to date.` 或者一堆文件名就是成功。

---

## 第 4 步：填 .env 文件（5 分钟）⭐ 最关键

### 4.1 备份旧的 .env

```bash
cp .env .env.backup.$(date +%Y%m%d)
```

### 4.2 用 nano 打开 .env

```bash
nano .env
```

### 4.3 找到下面这几行并填好

按 `Ctrl+W` 搜索 `POLY_PRIVATE_KEY`，然后修改成：

```
POLY_PRIVATE_KEY=0xabc123...你刚才复制的私钥...def
POLY_FUNDER=0x你刚才复制的funder地址
POLY_CHAIN_ID=137
POLY_SIGNATURE_TYPE=2
```

⚠️ 注意：
- 私钥前面要有 `0x`
- 等号两边**不要有空格**
- 不要加引号

### 4.4 同时确认下面这些（先保持模拟模式）

```
TRADING_ENABLED=true
DRY_RUN=true
BET_SIZE_USDC=5
```

### 4.5 保存退出

按 `Ctrl+O` → 回车（保存）→ `Ctrl+X` （退出）

### 4.6 验证 .env 没有泄露到 git

```bash
grep -l POLY_PRIVATE_KEY .gitignore && echo "✅ .env 已被 git 忽略" || echo "❌ 危险！.env 可能会被提交"
```

应该看到 `.env`（说明 .env 在 .gitignore 里），如果不是，**立刻停止**并告诉我。

---

## 第 5 步：链上一次性授权（5 分钟，会消耗 ~$0.3 MATIC）

> 这一步是告诉 Polymarket 的智能合约："我同意你从我钱包里扣 USDC、移动我的份额"。
> **每个钱包一辈子只需要做一次。**

### 5.1 先安装一下 web3 库（如果没装）

```bash
docker compose run --rm bot pip install web3 python-dotenv
```

### 5.2 检查授权状态

```bash
docker compose run --rm bot python3 scripts/setup_allowance.py --check
```

输出会列出 6 项检查（USDC × 3 个合约 + ERC1155 × 3 个合约）。
- ✅ 表示已授权
- ❌ 表示需要授权

### 5.3 实际发起授权

```bash
docker compose run --rm bot python3 scripts/setup_allowance.py
```

会逐笔发链上交易，每笔等 30 秒左右。看到 `🎉 授权完成` 就成功。

> 如果失败提示 `MATIC 余额不足`，就去 polygonscan 上从其他钱包/交易所充一点点 MATIC（5 个就够了）到你的 funder 地址。

---

## 第 6 步：装 chrony 对时（2 分钟）

末端狙击对时间精度敏感，必须装时钟同步。

```bash
sudo apt update
sudo apt install -y chrony
sudo systemctl enable --now chrony
chronyc tracking | grep -E "Last offset|RMS offset"
```

`Last offset` 应该是几毫秒（ms）级别的，比如 `Last offset : -0.000123 seconds`。如果是几秒，等 5 分钟再看一次。

---

## 第 7 步：跑 DRY_RUN 1 小时（必做！）

这一步是"真接入 Polymarket，但不真下单"，验证决策逻辑没问题。

### 7.1 启动模拟模式

```bash
bash deploy/go_live.sh dry
```

这个命令会：
1. 检查环境（代码、.env、Docker、chrony）
2. 自动把 `.env` 改成 `DRY_RUN=true TRADING_ENABLED=true`
3. 启动 bot 容器

### 7.2 看日志

```bash
bash deploy/go_live.sh logs
```

按 `Ctrl+C` 退出日志查看（不会停 bot）。

### 7.3 你应该看到这些日志（说明工作正常）

```
[INFO] Polymarket Sniper Bot - BTC 5m End Snipe
[INFO] ⚠️  DRY_RUN=true，模拟模式（不会真实下单）
[INFO] 🔐 初始化 CLOB 客户端 (chain_id=137, signature_type=2, ...)
[INFO] 🔑 已派生 L2 API 凭据
[INFO] 当前窗口: 剩余 134s, UP=0.52, DOWN=0.48
...
[INFO] 🔬 DRY-RUN: UP @ 0.570 x 8.7720 份额 (~5.00 USDC, 跳过真实下单)
```

**至少跑满 1 小时**（5 分钟一个窗口，能见到约 12 次决策）。每隔 15 分钟用 `bash deploy/go_live.sh status` 看一眼状态。

### 7.4 1 小时后的检查清单

- [ ] 日志里没有 `ERROR` 级别的异常
- [ ] 至少看到 1 次 `🔬 DRY-RUN: UP/DOWN @ ...` 的入场决策
- [ ] `bash deploy/go_live.sh status` 显示 `circuit_breaker: False`
- [ ] 没有 `余额不足 / 授权不足` 的告警

如果上面全过 → 进入第 8 步。
如果有问题 → 截图发给我或停下来 (`bash deploy/go_live.sh stop`)。

---

## 第 8 步：⚠️ 实盘小额验证 24 小时

> 从这一步开始，机器人会**真实花你钱**！默认每单 5 USDC（最小）。
> 一天大概 200~500 个 BTC 5 分钟窗口，所以 24 小时可能下 5~50 单。
> 即使全部输光，最多损失也就 100~250 USDC。

### 8.1 切到实盘

```bash
bash deploy/go_live.sh live
```

它会让你输入 `YES I AM SURE` 才启动。这是故意的"反误触保险"。

### 8.2 监控建议

第一个小时，**坐在电脑前盯着**：

```bash
bash deploy/go_live.sh logs
```

看到第一笔真实成交（`✅ 订单已提交` + `🎯 订单已完全成交`）确认：
1. 你的 Polymarket 账户里份额数量增加了
2. USDC 余额减少了对应金额

之后可以离开，每隔几小时看一下：

```bash
bash deploy/go_live.sh status
```

### 8.3 紧急停机

任何时候发现异常（亏损过快、日志报错、bot 卡住）：

```bash
bash deploy/go_live.sh stop
```

---

## 第 9 步：24 小时后评估（5 分钟）

跑满 24 小时后，执行：

```bash
bash deploy/go_live.sh status
```

看这几个数字：

| 指标 | 健康标准 |
|------|---------|
| 今日交易数 | 5~50 之间正常 |
| 累计 PnL | 不要求一定为正，但**单日亏损不应超过 -20 USDC**（默认熔断阈值） |
| circuit_breaker | 应该是 `False`；如果是 `True` 说明触发了熔断器 |
| 历史持仓 | 数量应该 ≈ 今日交易数（说明结算正常） |

### 9.1 PnL 闭环验证

打开你的 Polymarket 账户网页：
1. 历史交易里能看到机器人的每一笔成交
2. 算一下盈亏总额
3. 跟 `bash deploy/go_live.sh status` 显示的 `累计 PnL` 对比，**误差应该在 10% 以内**（手续费等原因）

如果对得上 → ✅ 可以放大下注规模，去改 `.env` 里 `BET_SIZE_USDC=10` 或 `20`，重启即可。
如果对不上 → 把日志（`docker compose logs --tail=500 bot > /tmp/log.txt`）发给我看。

---

## 🎯 常用命令速查

```bash
# 进项目目录（每次开终端先做这步）
cd /opt/polymarket-bot

# 看现在状态/PnL
bash deploy/go_live.sh status

# 看实时日志（Ctrl+C 退出，不会停 bot）
bash deploy/go_live.sh logs

# 模拟模式启动
bash deploy/go_live.sh dry

# 实盘启动（要敲 YES I AM SURE 确认）
bash deploy/go_live.sh live

# 停机器人
bash deploy/go_live.sh stop

# 改下注规模
nano .env   # 改 BET_SIZE_USDC=N，Ctrl+O 保存，Ctrl+X 退出
docker compose restart bot

# 看链上授权状态
docker compose run --rm bot python3 scripts/setup_allowance.py --check
```

---

## ❓ 常见问题

### Q1：日志显示 `获取Binance价格失败`？
机器人需要访问 api.binance.com 拿 BTC 实时价。
- 国内服务器可能要用代理；
- AWS Tokyo VPS 一般直连可以。
检查：`curl -s https://api.binance.com/api/v3/ping`

### Q2：日志显示 `USDC 余额不足`？
说明你 funder 钱包里 USDC.e 不够。去 Polymarket 充值或者从其他钱包转 USDC.e (Polygon 链) 到 funder 地址。

### Q3：日志显示 `USDC 授权不足`？
跑一下：`docker compose run --rm bot python3 scripts/setup_allowance.py`

### Q4：触发熔断器了 (`circuit_breaker: True`)
说明今日亏损 > `DAILY_LOSS_LIMIT_USDC`（默认 20）。
- 不是 bug，是保护
- 修复后重启会自动重置：第二天 0 点 UTC 自动解除

### Q5：怎么开 Telegram 告警？
1. 找 [@BotFather](https://t.me/BotFather) → `/newbot` 拿一个 `bot_token`
2. 把 bot 拉进一个群，群里发条消息
3. 浏览器打开 `https://api.telegram.org/bot<你的token>/getUpdates`，找 `chat` 里的 `id`
4. `nano .env` 填：
   ```
   TELEGRAM_BOT_TOKEN=你的token
   TELEGRAM_CHAT_ID=你的chat_id
   ```
5. `docker compose restart bot`

---

## 附录 A：怎么把 USDC 提到自己钱包

如果你的钱在 Polymarket 网页内（不是自己的钱包），你需要：

1. **不需要提！** Polymarket 内部余额 = 你的 funder 钱包 USDC.e 余额。机器人直接用这个余额下单。
2. **需要 MATIC 付 gas** → 用任何交易所提 MATIC 到你的 funder 地址（Polygon 网络）。

最少：1~5 个 MATIC（够授权 + 几个月运行）。

---

## 附录 B：紧急联系/止损

如果发现：
- 24 小时亏损超过 50 USDC
- 日志反复报错 / bot 不响应
- Polymarket 账户出现你不认识的交易

**立刻执行**：

```bash
cd /opt/polymarket-bot
bash deploy/go_live.sh stop
```

然后到 Polymarket 网页手动撤掉所有挂单，并把 .env 里的 `TRADING_ENABLED=false`。

---

> 任何步骤不确定？把当前命令的输出截图发给 AI 助手，逐字描述你看到的现象，会帮你诊断。
