"use strict";

/**
 * scripts/watch-grid-dryrun.js
 * Continuous watch mode: poll the orderbook on a fixed interval and
 * re-print the grid plan each cycle — without placing any orders.
 *
 * Usage:
 *   node scripts/watch-grid-dryrun.js
 *   SLUG=btc-updown-5m-1773753900 INTERVAL_MS=3000 node scripts/watch-grid-dryrun.js
 *
 * Press Ctrl+C to stop.
 */

const { loadConfig } = require("../lib/config");
const { log, sleep } = require("../lib/utils");
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

  log.info(`Watch mode started — slug: ${slug}  interval: ${cfg.intervalMs} ms`);
  log.info("Press Ctrl+C to stop.\n");

  // Fetch market metadata once (token IDs don't change within a session)
  log.info("Fetching market metadata…");
  const market = await fetchMarketFromEventPage(slug);
  log.info(`Market: ${market.question}`);

  const tokenMap = getUpDownMappingFromMarket(market);
  const upTokenId = tokenMap["Up"];
  const downTokenId = tokenMap["Down"];

  if (!upTokenId || !downTokenId) {
    log.error("Could not find Up/Down token IDs:", tokenMap);
    process.exit(1);
  }

  let cycle = 0;
  let consecutiveErrors = 0;

  while (true) {
    cycle++;
    try {
      const { upBook, downBook } = await fetchBothBooks(upTokenId, downTokenId);

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

      console.log(`\n[cycle ${cycle}] ${new Date().toISOString()}`);
      console.log("─".repeat(72));
      for (const o of plan) {
        console.log(
          `  ${o.side.padEnd(4)}  outcome=${o.outcome.padEnd(4)}  price=${String(o.price).padEnd(6)}  size=${o.size}  mid=${o.mid.toFixed(4)}`,
        );
      }
      console.log(`  Total: ${plan.length} orders`);

      consecutiveErrors = 0;
    } catch (err) {
      consecutiveErrors++;
      log.error(`Cycle ${cycle} error (${consecutiveErrors}/${cfg.maxErrors}): ${err.message}`);
      if (consecutiveErrors >= cfg.maxErrors) {
        log.error("Too many consecutive errors — stopping.");
        process.exit(1);
      }
    }

    await sleep(cfg.intervalMs);
  }
})().catch((err) => {
  log.error(err.message || err);
  process.exit(1);
});
