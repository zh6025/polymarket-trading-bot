# Railway vs Vultr：部署方式对比

> 本文回答一个常见问题：同样都可以运行 Polymarket Trading Bot，在 **Railway** 和 **Vultr** 上部署有什么本质区别？应该选哪个？

---

## 一句话总结

| | Railway | Vultr |
|---|---|---|
| **是什么** | PaaS（平台即服务）——托管式云平台，帮你管理服务器 | VPS（虚拟私有服务器）——你租一台完整的 Linux 服务器，自行管理 |
| **适合谁** | 不想管服务器、VPN 环境受限、想快速上线的用户 | 想完全控制服务器、了解 Linux 运维、需要更低成本的用户 |

---

## 详细对比

### 1. 访问控制台

| 维度 | Railway | Vultr |
|---|---|---|
| 登录方式 | GitHub OAuth（一键授权，不需注册新账号） | 邮箱 + 密码注册 |
| VPN 稳定性 | **最好** — 基于 GitHub 和国际 CDN，几乎无封锁 | **部分受限** — 部分 VPN 线路下控制台卡顿/无响应 |
| 控制台类型 | 全 Web，无需任何本地工具 | 全 Web，但下一步 SSH 需要本地终端 |

> **关键差异**：如果你在中国大陆或 VPN 环境下发现 Vultr 控制台点击没有反应（常见问题），Railway 不会有这个问题。

---

### 2. 部署流程

| 步骤 | Railway | Vultr |
|---|---|---|
| 需要 SSH 吗 | ❌ 完全不需要 | ✅ 必须（用于登录服务器填写密钥） |
| 需要命令行吗 | ❌ 完全不需要 | ✅ 必须（`nano`、`systemctl` 等） |
| 代码如何部署 | 连接 GitHub 仓库，每次 push 自动部署 | 用 Startup Script 在服务器启动时运行安装脚本 |
| 配置在哪里 | Railway 控制台 → Variables（网页填写） | 服务器上的 `.env` 文件（SSH 进去用编辑器改） |
| 首次部署时间 | **约 5 分钟**（浏览器全程完成） | **约 10-15 分钟**（等服务器启动 + SSH + 安装） |

---

### 3. 数据持久化

| 维度 | Railway | Vultr |
|---|---|---|
| SQLite 数据库存储位置 | Railway Volume（需手动添加，挂载到 `/data`） | 服务器本地磁盘 `/data/trading_bot.db`（自动，无需配置） |
| 重启后数据是否保留 | ✅ 保留（前提：已添加 Volume） | ✅ 保留（服务器磁盘持久） |
| 删除服务/服务器后数据 | ❌ Volume 一起删除 | ❌ 磁盘一起删除 |
| 数据库文件导出 | 较难（Railway 不直接提供文件下载） | 简单（`scp root@IP:/data/trading_bot.db ./` 直接下载） |

> **关键差异**：如果你需要定期下载数据库做本地分析，Vultr 更方便（直接 `scp`）；Railway 需要在代码中实现导出接口或通过日志读取数据。

---

### 4. 代码更新 / CI/CD

| 维度 | Railway | Vultr |
|---|---|---|
| 推送代码后如何更新 | **自动** — push 到 GitHub → Railway 自动检测并重新部署 | **手动** — SSH 进服务器 → `git pull` → `systemctl restart` |
| 回滚 | Railway 控制台一键回滚到任意历史 Deployment | `git checkout` + 手动重启 |
| 零停机部署 | Railway 内置滚动更新 | 重启期间有短暂中断（约 2-5 秒） |

---

### 5. 费用

| 维度 | Railway | Vultr |
|---|---|---|
| 最低月费 | $5/月（Hobby 计划，包含基础资源） | $6/月（最低配 1 vCPU / 1 GB RAM） |
| 计费方式 | 按实际资源使用量计费（CPU + 内存 + 存储 + 出站流量） | 按小时计费，包月价格固定 |
| 免费额度 | $5 一次性 Trial 额度（约够运行 1-2 个月） | 无固定免费额度（偶有新用户优惠） |
| 存储费用 | 单独计费（Volume，约 $0.25/GB/月） | 包含在月费中（25 GB SSD 已包含在 $6/月） |
| 估算月费（Bot 运行） | **约 $3-6/月**（1 vCPU / 512 MB 使用量 + 1 GB Volume） | **$6/月**（固定） |
| 付款方式 | 信用卡 / 借记卡 | 信用卡 / PayPal / **加密货币（比特币等）** |

> **关键差异**：Vultr 支持**加密货币付款**（对不想绑定信用卡的用户更方便）。Railway 仅支持信用卡/借记卡。

---

### 6. 运维 & 调试

| 维度 | Railway | Vultr |
|---|---|---|
| 查看日志 | Railway 控制台 → Logs 标签，实时滚动，支持关键词搜索 | `journalctl -u polymarket-bot -f` 或 `docker logs` |
| 修改配置 | Railway 控制台改 Variables → 自动重新部署 | SSH → `nano .env` → `systemctl restart` |
| 暂停机器人 | 控制台 → "Pause Service"（一键，不删数据） | `systemctl stop polymarket-bot`（SSH） |
| 重启机器人 | 控制台 → "Redeploy" 或改一个 Variable | `systemctl restart polymarket-bot`（SSH） |
| 崩溃自动重启 | ✅ 内置（railway.toml 配置，10 次重试） | ✅ systemd 配置（`Restart=always`） |
| 访问服务器文件系统 | ❌ 无法直接访问 | ✅ 完整 SSH 访问 |

---

### 7. 安全性

| 维度 | Railway | Vultr |
|---|---|---|
| 私钥（PK）存储 | Railway Variables（加密存储，不出现在代码/日志中） | `.env` 文件（服务器磁盘，需手动限制权限） |
| 服务器暴露面 | **无**（Railway 管理基础设施，无公开 IP 给你） | 有公开 IP，需要自行配置防火墙、禁用 root 密码登录 |
| 服务器安全加固 | Railway 负责（你无需操作） | **你负责**（安装 fail2ban、配置 ufw、禁用密码 SSH 等） |
| 镜像/依赖更新 | 每次 push 自动重建 Docker 镜像 | 需要手动 `git pull && docker rebuild` 或 `apt upgrade` |

> **关键差异**：Vultr 给你一台完整服务器，意味着你既拥有完全控制权，也要承担安全维护责任。Railway 将基础设施安全交给平台，你只需要管好自己的 API 密钥。

---

### 8. 控制权 & 灵活性

| 维度 | Railway | Vultr |
|---|---|---|
| 操作系统访问 | ❌ 无（容器环境，不暴露 OS） | ✅ 完整 root 权限 |
| 安装额外软件 | ❌ 只能通过 Dockerfile 添加 | ✅ 任意 `apt install` |
| 运行多个进程 | 需要多个 Railway Service | 在同一台服务器上随意配置 |
| 自定义网络 / IP | ❌（Railway 分配） | ✅ 可绑定固定 IP（Vultr 支持 Reserved IP） |
| 数据库可直接访问 | 较难 | ✅ 直接 `sqlite3 /data/trading_bot.db` |

---

## 选择建议

### 选 Railway 如果：

- ✅ 在 VPN 环境下，Vultr / DigitalOcean 控制台点击无响应
- ✅ 不熟悉 Linux / SSH / 命令行
- ✅ 想要最快上手（5 分钟内 → 模拟模式运行）
- ✅ 希望 push 代码后自动部署，无需手动更新
- ✅ 不想承担服务器安全维护责任
- ✅ 可以接受信用卡/借记卡付款

### 选 Vultr 如果：

- ✅ 熟悉 Linux 和 SSH 操作
- ✅ 需要完整的服务器访问权限（调试、额外工具）
- ✅ 想要导出 SQLite 数据库做本地分析
- ✅ 需要用**加密货币**（比特币等）付款
- ✅ 想要在同一台服务器上运行其他程序
- ✅ 月费完全固定（不想按用量计费）

---

## 架构差异示意图

```
┌─────────────────────────────────────────┐
│              Railway（PaaS）            │
│                                         │
│  你的电脑/手机浏览器                    │
│       │                                 │
│       ▼                                 │
│  Railway 控制台（Web）                  │
│       │ 连接                            │
│       ▼                                 │
│  你的 GitHub 仓库 ──push──▶ 自动部署   │
│                              │          │
│                              ▼          │
│               Railway 托管环境          │
│             ┌──────────────────────┐    │
│             │   Docker 容器         │    │
│             │   runner.py           │    │
│             │   /data (Volume)      │    │
│             └──────────────────────┘    │
│          （底层服务器由 Railway 管理）   │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│              Vultr（VPS）               │
│                                         │
│  你的电脑/手机浏览器                    │
│       │                                 │
│       ▼                                 │
│  Vultr 控制台（Web）                   │
│  → 创建服务器 + 粘贴 Startup Script     │
│                                         │
│  你的电脑终端（SSH）                    │
│       │                                 │
│       ▼                                 │
│  Vultr 服务器（Ubuntu VPS）             │
│  ┌──────────────────────────────────┐   │
│  │  /opt/polymarket-bot/            │   │
│  │    runner.py                     │   │
│  │    .env  ← 你来编辑              │   │
│  │  /data/trading_bot.db            │   │
│  │  systemd 服务（自动重启）         │   │
│  └──────────────────────────────────┘   │
│       （整台服务器由你完全控制）         │
└─────────────────────────────────────────┘
```

---

## 常见问题

### Q: Railway 上的机器人和 Vultr 上的机器人，交易行为有区别吗？

**没有区别。** 两者都运行同一份代码（`runner.py`），通过相同的环境变量配置。交易策略、风控逻辑完全一致。唯一的区别是**基础设施的管理方式**不同。

---

### Q: 两个平台的网络延迟有区别吗？

有轻微差别。

- **Vultr New Jersey (EWR)** 节点到 Polymarket CLOB 服务器（美国东部）延迟约 5-20 ms
- **Railway** 默认部署在 US 区域，延迟通常在 10-30 ms

对于本策略（5 分钟蜡烛 + 轮询间隔 1 秒），两者的延迟差异可忽略不计。如果你需要做极端高频套利，两个平台都不适合，需要专用托管服务。

---

### Q: 如果我在 Railway 上部署了，还需要 Vultr 吗？

不需要。Railway 完全可以替代 Vultr 用于运行这个机器人。两者都能完整运行所有功能。选择其中一个即可。

---

### Q: 我能同时在两个平台运行同一个账号的机器人吗？

⚠️ **不推荐。** 两个机器人实例会共享同一个 Polymarket 账号，可能导致：

- 订单重复下单、仓位计算错误
- 风控限制（`DAILY_MAX_LOSS_USDC`）被绕过
- PnL 记录混乱（两个独立的 SQLite 数据库）

如果你想测试两个平台，可以使用不同的账号，或让一个跑模拟模式（`TRADING_MODE=dry_run`），另一个跑实盘。

---

## 相关文档

- [Railway 完整部署教程](railway-deploy.md)
- [Vultr 完整部署教程](vultr-deploy.md)
- [DigitalOcean 部署教程](digitalocean-deploy.md)
- [项目 README（主文档）](../README.md)
