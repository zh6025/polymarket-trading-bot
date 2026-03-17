
scripts/watch-grid-dryrun.js v2
const { sleep } = require("../lib/http");
const { fetchMarketFromEventPage, getUpDownMappingFromMarket, fetchBook, bestBidAsk } = require("../lib/polymarket");

const SLUG = process.env.SLUG || "btc-updown-5m-1773753900";
const INTERVAL_MS = Number(process.env.INTERVAL_MS || 5000);
