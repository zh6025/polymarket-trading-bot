#!/usr/bin/env node
"use strict";

/**
 * bot-runner.js
 * Main entry point for the Polymarket grid trading bot.
 *
 * The bot polls the orderbook on a fixed interval, computes the current
 * grid order plan, checks risk limits, and (when not in dry-run mode)
 * submits orders to the CLOB.
 *
 * Usage:
 *   node bot-runner.js              # uses .env for config
 *   node bot-runner.js --dry-run    # override DRY_RUN=true
 *   node bot-runner.js --verbose    # enable DEBUG output
 *
 * Environment variables (see .env.example for the full list):
 *   SLUG, SERIES_SLUG, LEVELS_EACH_SIDE, GRID_STEP, ORDER_SIZE,
 *   TRADE_BOTH_OUTCOMES, INTERVAL_MS, MAX_ERRORS, DRY_RUN,
 *   MAX_DAILY_LOSS_USDC, MAX_POSITION_USDC
 */

const { loadConfig } = require("./lib/config");
const { log, sleep } = require("./lib/utils");
const {
  fetchMarketFromEventPage,
  getUpDownMappingFromMarket,
  fetchBothBooks,
  findLatestOpenEvent,
} = require("./lib/polymarket");
const { buildUpDownGridPlan } = require("./lib/strategy");
const { RiskManager } = require("./lib/risk");

// ── CLI flag parsing ─────────────────────────────────────────────────────────

const args = process.argv.slice(2);
if (args.includes("--dry-run")) process.env.DRY_RUN = "true";
if (args.includes("--verbose")) process.env.DEBUG = "1";
if (args.includes("--help") || args.includes("-h")) {
  console.log(`
Usage: node bot-runner.js [options]

Options:
  --dry-run   Print order plan without submitting (overrides DRY_RUN env var)
  --verbose   Enable debug logging (sets DEBUG=1)
  --help, -h  Show this help message

Configuration is read from environment variables / .env file.
See .env.example for the full list of available settings.
`);
  process.exit(0);
}

// ── Main ─────────────────────────────────────────────────────────────────────

async function main() {
  const cfg = loadConfig();
  const risk = new RiskManager({
    maxDailyLossUsdc: cfg.maxDailyLossUsdc,
    maxPositionUsdc: cfg.maxPositionUsdc,
  });

  log.info("═".repeat(60));
  log.info("  Polymarket Grid Bot  starting up");
  log.info("═".repeat(60));
  log.info(`  dry-run          : ${cfg.dryRun}`);
  log.info(`  series slug      : ${cfg.seriesSlug}`);
  log.info(`  event slug       : ${cfg.slug || "(auto-discover)"}`);
  log.info(`  levels each side : ${cfg.levelsEachSide}`);
  log.info(`  grid step        : ${cfg.gridStep}`);
  log.info(`  order size       : ${cfg.orderSize} USDC`);
  log.info(`  trade both sides : ${cfg.tradeBothOutcomes}`);
  log.info(`  poll interval    : ${cfg.intervalMs} ms`);
  log.info(`  max daily loss   : ${cfg.maxDailyLossUsdc} USDC`);
  log.info(`  max position     : ${cfg.maxPositionUsdc} USDC`);
  log.info("─".repeat(60));

  if (!cfg.dryRun && (!cfg.apiKey || !cfg.privateKey)) {
    log.error("Live trading requires PM_API_KEY and PM_PRIVATE_KEY to be set.");
    log.error("Either set those env vars or run with --dry-run.");
    process.exit(1);
  }

  // ── Resolve slug ────────────────────────────────────────────────────────

  let slug = cfg.slug;
  if (!slug) {
    log.info(`No SLUG set — auto-discovering latest open event for series "${cfg.seriesSlug}"…`);
    const event = await findLatestOpenEvent(cfg.seriesSlug);
    if (!event) {
      log.error(`No open events found for series "${cfg.seriesSlug}". Exiting.`);
      process.exit(1);
    }
    slug = event.slug;
    log.info(`Auto-discovered event slug: ${slug}`);
  }

  // ── Fetch market metadata (token IDs don't change within a session) ────

  log.info(`Fetching market metadata for: ${slug}`);
  const market = await fetchMarketFromEventPage(slug);
  log.info(`Market : ${market.question}`);
  log.info(`  restricted=${market.restricted}  acceptingOrders=${market.acceptingOrders}`);

  const tokenMap = getUpDownMappingFromMarket(market);
  const upTokenId = tokenMap["Up"];
  const downTokenId = tokenMap["Down"];

  if (!upTokenId || !downTokenId) {
    log.error("Could not resolve Up/Down token IDs:", tokenMap);
    process.exit(1);
  }
  log.info(`Up   tokenId : ${upTokenId}`);
  log.info(`Down tokenId : ${downTokenId}`);
  log.info("─".repeat(60));

  // ── Poll loop ────────────────────────────────────────────────────────────

  let cycle = 0;
  let consecutiveErrors = 0;

  while (true) {
    cycle++;
    log.debug(`cycle ${cycle} start`);

    try {
      // ── Risk check ───────────────────────────────────────────────────────
      if (risk.halted) {
        log.warn(`Circuit breaker is active — skipping cycle ${cycle}. Status: ${JSON.stringify(risk.status())}`);
        await sleep(cfg.intervalMs);
        continue;
      }

      // ── Fetch orderbooks ─────────────────────────────────────────────────
      const { upBook, downBook } = await fetchBothBooks(upTokenId, downTokenId);

      // ── Build order plan ─────────────────────────────────────────────────
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

      log.info(`[cycle ${cycle}] Generated ${plan.length} orders  tick=${upBook.tick_size}  minSize=${upBook.min_order_size}`);

      if (cfg.dryRun) {
        // Print plan and continue
        for (const o of plan) {
          const check = risk.checkOrder({ size: o.size, price: o.price });
          const flag = check.allowed ? "✓" : `✗ (${check.reason})`;
          log.info(`  [DRY-RUN] ${o.side.padEnd(4)} ${o.outcome.padEnd(4)} price=${String(o.price).padEnd(6)} size=${o.size}  mid=${o.mid.toFixed(4)}  ${flag}`);
        }
      } else {
        // Live trading placeholder
        // TODO: integrate @polymarket/clob-client to submit orders
        log.warn("Live order submission is not yet implemented. Use --dry-run.");
      }

      log.debug(`Risk status: ${JSON.stringify(risk.status())}`);
      consecutiveErrors = 0;
    } catch (err) {
      consecutiveErrors++;
      log.error(`Cycle ${cycle} error (${consecutiveErrors}/${cfg.maxErrors}): ${err.message}`);
      if (consecutiveErrors >= cfg.maxErrors) {
        log.error("Too many consecutive errors — bot stopping.");
        process.exit(1);
      }
    }

    await sleep(cfg.intervalMs);
  }
}

main().catch((err) => {
  log.error("Fatal error:", err.message || err);
  process.exit(1);
});
