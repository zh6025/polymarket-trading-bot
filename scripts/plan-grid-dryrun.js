"use strict";

/**
 * scripts/plan-grid-dryrun.js
 * One-shot grid dry-run: fetch the current orderbook and print the proposed
 * order plan without placing any orders.
 *
 * Usage:
 *   node scripts/plan-grid-dryrun.js
 *   SLUG=btc-updown-5m-1773753900 LEVELS_EACH_SIDE=3 node scripts/plan-grid-dryrun.js
 */

const { loadConfig } = require("../lib/config");
const { log } = require("../lib/utils");
const {
  fetchMarketFromEventPage,
  getUpDownMappingFromMarket,
  fetchBothBooks,
} = require("../lib/polymarket");
const { buildUpDownGridPlan } = require("../lib/strategy");

(async () => {
  const cfg = loadConfig();

  const slug = cfg.slug;
  if (!slug) {
    log.error("No SLUG configured. Set SLUG env var or add to .env");
    process.exit(1);
  }

  log.info(`Fetching market data for slug: ${slug}`);
  const market = await fetchMarketFromEventPage(slug);
  log.info(`Market: ${market.question}`);
  log.info(`  restricted=${market.restricted}  acceptingOrders=${market.acceptingOrders}`);

  const tokenMap = getUpDownMappingFromMarket(market);
  const upTokenId = tokenMap["Up"];
  const downTokenId = tokenMap["Down"];

  if (!upTokenId || !downTokenId) {
    log.error("Could not find Up/Down token IDs in market object");
    log.error("tokenMap:", tokenMap);
    process.exit(1);
  }

  log.info(`Up   tokenId: ${upTokenId}`);
  log.info(`Down tokenId: ${downTokenId}`);

  const { upBook, downBook } = await fetchBothBooks(upTokenId, downTokenId);

  log.info(`tick_size=${upBook.tick_size}  min_order_size=${upBook.min_order_size}`);

  const plan = buildUpDownGridPlan({
    upBook,
    downBook,
    upTokenId,
    downTokenId,
    levelsEachSide: cfg.levelsEachSide,
    gridStep: cfg.gridStep,
    orderSize: cfg.orderSize,
    tradeBothOutcomes: cfg.tradeBothOutcomes,
  });

  console.log("\nDRY-RUN ORDER PLAN (no orders placed):");
  console.log("─".repeat(72));
  for (const o of plan) {
    const midLabel = `(mid ${o.mid.toFixed(4)})`;
    console.log(
      `  ${o.side.padEnd(4)}  outcome=${o.outcome.padEnd(4)}  price=${String(o.price).padEnd(6)}  size=${o.size}  ${midLabel}`,
    );
  }
  console.log("─".repeat(72));
  console.log(`Total orders: ${plan.length}`);
})().catch((err) => {
  log.error(err.message || err);
  process.exit(1);
});
