require('dotenv').config();
const { ClobClient } = require('@polymarket/clob-client');
const { createWalletClient, http } = require('viem');
const { privateKeyToAccount } = require('viem/accounts');
const { polygon } = require('viem/chains');

const HOST = 'https://clob.polymarket.com';
const CHAIN_ID = 137;
const UP_TOKEN_ID = '17888749046052387768285639771190861611265286883094765303527288263281761615943';
const RPC_URL = process.env.POLYGON_RPC_URL || 'https://polygon-rpc.com';

async function main() {
  const pk = process.env.PRIVATE_KEY;
  if (!pk) throw new Error('Missing env PRIVATE_KEY');

  const account = privateKeyToAccount(pk);
  console.log('wallet address:', account.address);

  const walletClient = createWalletClient({
    account,
    chain: polygon,
    transport: http(RPC_URL),
  });

  const client = new ClobClient(HOST, CHAIN_ID, walletClient);

  const creds = await client.createOrDeriveApiKey();
  console.log('createOrDeriveApiKey OK. fields:', Object.keys(creds || {}));

  const book = await client.getOrderBook(UP_TOKEN_ID);
  console.log('top bid:', book?.bids?.[0]);
  console.log('top ask:', book?.asks?.[0]);
  console.log('tick_size:', book?.tick_size, 'min_order_size:', book?.min_order_size);
}

main().catch((e) => {
  console.error('FAILED:', e?.message || e);
  if (e?.response?.data) console.error('response.data:', e.response.data);
  process.exit(1);
});
