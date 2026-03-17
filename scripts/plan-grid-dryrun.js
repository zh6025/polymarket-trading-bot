scripts/plan-grid-dryrun.js
v2
const { fetchMarketFromEventPage, getUpDownMappingFromMarket, fetchBook, bestBidAsk } = require("../lib/polymarket");

const SLUG = process.env.SLUG || "btc-updown-5m-1773753900";

// 参数（可通过 env 覆盖）
const LEVELS_EACH_SIDE = Number(process.env.LEVELS_EACH_SIDE || 5);
