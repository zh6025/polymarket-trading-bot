"use strict";

/**
 * lib/config.js
 * Centralised configuration loaded from environment variables.
 * Call `loadConfig()` once at startup (after dotenv.config()).
 */

const path = require("path");

// Load .env if present (silently skip if not found)
try {
  require("dotenv").config({ path: path.resolve(process.cwd(), ".env") });
} catch (_) {
  // dotenv not available — continue with existing env
}

/**
 * Read an environment variable, falling back to `defaultValue`.
 * Throws if the variable is missing and no default is provided.
 * @param {string} key
 * @param {string|undefined} [defaultValue]
 * @returns {string}
 */
function env(key, defaultValue) {
  const v = process.env[key];
  if (v !== undefined && v !== "") return v;
  if (defaultValue !== undefined) return defaultValue;
  throw new Error(`Required environment variable "${key}" is not set. See .env.example.`);
}

/**
 * Build and return the application configuration object.
 * All values can be overridden via environment variables.
 * @returns {object}
 */
function loadConfig() {
  return {
    // ── Market ────────────────────────────────────────────────────────────
    /** Polymarket event slug to trade, e.g. "btc-updown-5m-1773753900" */
    slug: env("SLUG", ""),

    /** Series slug used when auto-discovering the latest open event */
    seriesSlug: env("SERIES_SLUG", "btc-up-or-down-5m"),

    // ── Strategy ──────────────────────────────────────────────────────────
    /** Number of grid levels on each side of mid */
    levelsEachSide: Number(env("LEVELS_EACH_SIDE", "5")),

    /** Grid price step — must be a multiple of tick_size */
    gridStep: Number(env("GRID_STEP", "0.02")),

    /** USDC order size per level */
    orderSize: Number(env("ORDER_SIZE", "5")),

    /** Whether to trade both Up and Down outcomes */
    tradeBothOutcomes: env("TRADE_BOTH_OUTCOMES", "true") !== "false",

    // ── Bot loop ──────────────────────────────────────────────────────────
    /** Polling interval in milliseconds */
    intervalMs: Number(env("INTERVAL_MS", "5000")),

    /** Maximum number of consecutive fetch errors before stopping */
    maxErrors: Number(env("MAX_ERRORS", "5")),

    // ── Risk ──────────────────────────────────────────────────────────────
    /** Maximum daily loss in USDC before circuit breaker trips */
    maxDailyLossUsdc: Number(env("MAX_DAILY_LOSS_USDC", "50")),

    /** Maximum total open position in USDC */
    maxPositionUsdc: Number(env("MAX_POSITION_USDC", "200")),

    // ── Execution ─────────────────────────────────────────────────────────
    /** When true, print orders but do not submit them */
    dryRun: env("DRY_RUN", "true") !== "false",

    // ── Auth (optional — required for live trading) ────────────────────────
    /** Polymarket API key (CLOB auth) */
    apiKey: process.env.PM_API_KEY || "",

    /** Ethereum private key for signing orders */
    privateKey: process.env.PM_PRIVATE_KEY || "",
  };
}

module.exports = { loadConfig, env };
