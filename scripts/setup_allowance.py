#!/usr/bin/env python3
"""
scripts/setup_allowance.py — 链上一次性授权

在首次实盘交易之前，必须授权 Polymarket 的 Exchange / NegRisk Exchange / NegRisk Adapter
合约可以从你的钱包扣除 USDC.e（抵押品），并允许它们转移你的 ERC1155 conditional tokens。

用法（在装有 .env 的目录下）：
    python scripts/setup_allowance.py            # 检查 + 授权
    python scripts/setup_allowance.py --check    # 仅检查，不发交易

需要 .env 中：
    POLY_PRIVATE_KEY=0x...   # 你的钱包私钥（Polymarket Proxy 部署者）
    POLY_FUNDER=0x...        # 仅用于打印（实际授权来自私钥地址）
    POLYGON_RPC=https://polygon-rpc.com   # 可选，默认 polygon-rpc.com

⚠️ 重要：
1. 授权对象是 Polymarket 的 CLOB Exchange 合约，不是你的 funder 地址。
2. 授权金额设为 uint256.MAX（无限），常见做法。如担心，可改为定额。
3. 私钥地址必须是钱包本身（不是 proxy/funder 地址）。
"""
import argparse
import os
import sys

from dotenv import load_dotenv
from web3 import Web3

load_dotenv()

POLYGON_RPC = os.environ.get('POLYGON_RPC', 'https://polygon-rpc.com')
PRIVATE_KEY = os.environ.get('POLY_PRIVATE_KEY', '').strip()

# Polymarket 在 Polygon 上的合约（mainnet, chain_id=137）
# 参考：Polymarket 官方文档与 py_clob_client 源码
USDC_E_ADDRESS = Web3.to_checksum_address('0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174')
CTF_ADDRESS = Web3.to_checksum_address('0x4D97DCd97eC945f40cF65F87097ACe5EA0476045')
EXCHANGE_ADDRESS = Web3.to_checksum_address('0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E')      # CTFExchange
NEG_RISK_EXCHANGE = Web3.to_checksum_address('0xC5d563A36AE78145C45a50134d48A1215220f80a')   # NegRiskCtfExchange
NEG_RISK_ADAPTER = Web3.to_checksum_address('0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296')    # NegRiskAdapter

MAX_UINT256 = (1 << 256) - 1

ERC20_ABI = [
    {"constant": True, "inputs": [{"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}],
     "name": "allowance", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
    {"constant": False, "inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}],
     "name": "approve", "outputs": [{"name": "", "type": "bool"}], "type": "function"},
    {"constant": True, "inputs": [{"name": "owner", "type": "address"}],
     "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
]

ERC1155_ABI = [
    {"constant": True, "inputs": [{"name": "account", "type": "address"}, {"name": "operator", "type": "address"}],
     "name": "isApprovedForAll", "outputs": [{"name": "", "type": "bool"}], "type": "function"},
    {"constant": False, "inputs": [{"name": "operator", "type": "address"}, {"name": "approved", "type": "bool"}],
     "name": "setApprovalForAll", "outputs": [], "type": "function"},
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true', help='只检查授权状态，不发送交易')
    parser.add_argument('--rpc', default=POLYGON_RPC)
    args = parser.parse_args()

    if not PRIVATE_KEY:
        print("❌ 缺少 POLY_PRIVATE_KEY，请在 .env 中配置后重试。")
        sys.exit(1)

    w3 = Web3(Web3.HTTPProvider(args.rpc))
    if not w3.is_connected():
        print(f"❌ 无法连接 RPC: {args.rpc}")
        sys.exit(1)

    acct = w3.eth.account.from_key(PRIVATE_KEY)
    owner = acct.address
    print(f"📍 钱包地址: {owner}")
    print(f"📍 Polygon chain_id: {w3.eth.chain_id}")
    print(f"📍 RPC: {args.rpc}")

    matic_balance = w3.eth.get_balance(owner)
    print(f"💎 MATIC 余额: {w3.from_wei(matic_balance, 'ether'):.4f}")

    usdc = w3.eth.contract(address=USDC_E_ADDRESS, abi=ERC20_ABI)
    ctf = w3.eth.contract(address=CTF_ADDRESS, abi=ERC1155_ABI)

    usdc_balance = usdc.functions.balanceOf(owner).call()
    print(f"💵 USDC.e 余额: {usdc_balance / 1e6:.4f}")

    spenders = [
        ('Exchange (CTFExchange)', EXCHANGE_ADDRESS),
        ('NegRiskCtfExchange', NEG_RISK_EXCHANGE),
        ('NegRiskAdapter', NEG_RISK_ADAPTER),
    ]

    todo = []  # list of (kind, address, name)
    print("\n=== 授权状态检查 ===")
    for name, spender in spenders:
        cur = usdc.functions.allowance(owner, spender).call()
        ok = cur >= MAX_UINT256 // 2
        print(f"  {'✅' if ok else '❌'} USDC.allowance({name}): {cur}")
        if not ok:
            todo.append(('erc20', spender, name))

        approved = ctf.functions.isApprovedForAll(owner, spender).call()
        print(f"  {'✅' if approved else '❌'} CTF.isApprovedForAll({name}): {approved}")
        if not approved:
            todo.append(('erc1155', spender, name))

    if not todo:
        print("\n🎉 所有授权已就位，无需操作。")
        return

    if args.check:
        print(f"\n⚠️  --check 模式：发现 {len(todo)} 项需授权，已跳过发送交易。")
        sys.exit(2)

    print(f"\n🚀 准备发送 {len(todo)} 笔授权交易...")
    nonce = w3.eth.get_transaction_count(owner)

    for kind, spender, name in todo:
        if kind == 'erc20':
            tx = usdc.functions.approve(spender, MAX_UINT256).build_transaction({
                'from': owner,
                'nonce': nonce,
                'gas': 80000,
                'gasPrice': w3.eth.gas_price,
            })
        else:
            tx = ctf.functions.setApprovalForAll(spender, True).build_transaction({
                'from': owner,
                'nonce': nonce,
                'gas': 80000,
                'gasPrice': w3.eth.gas_price,
            })
        signed = acct.sign_transaction(tx)
        raw = getattr(signed, 'raw_transaction', None) or getattr(signed, 'rawTransaction', None)
        tx_hash = w3.eth.send_raw_transaction(raw)
        print(f"  → {kind} {name}: tx={tx_hash.hex()}，等待打包...")
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
        status = '✅ 成功' if receipt.status == 1 else '❌ 失败'
        print(f"    {status} (block={receipt.blockNumber}, gasUsed={receipt.gasUsed})")
        nonce += 1

    print("\n🎉 授权完成。请重新启动 bot。")


if __name__ == '__main__':
    main()
