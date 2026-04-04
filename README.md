# Polymarket BTC 5分钟机器人

这个仓库现在只保留一个最小可运行版本：`bot_continuous.py`。

它会持续轮询 Polymarket 的 BTC 5 分钟市场，读取盘口价格，按当前的简单价差逻辑生成挂单动作，并通过内存里的 `TradingEngine` 记录模拟订单状态。

## 当前保留内容

```text
bot_continuous.py      # 唯一保留的机器人入口
lib/config.py          # 基础运行配置
lib/polymarket_client.py
lib/trading_engine.py
lib/utils.py
tests/                 # 针对当前保留模块的测试
deploy/                # 部署脚本
```

## 快速开始

```bash
pip install -r requirements.txt
cp .env.example .env
python bot_continuous.py
```

## 环境变量

| 变量 | 默认值 | 说明 |
|---|---:|---|
| `DRY_RUN` | `true` | 是否使用模拟模式 |
| `ORDER_SIZE` | `5` | 默认下单数量 |
| `CHECK_INTERVAL_SEC` | `5` | 轮询间隔（秒） |

## 验证

```bash
python3 -m pytest tests -q
timeout 30 python3 bot_continuous.py
docker build -t polymarket-bot:test .
```
