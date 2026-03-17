"use strict";

/**
 * lib/strategy.js
 * Grid trading strategy engine.
 *
 * A symmetric grid is placed around the current mid price of each outcome.
 * Buy orders are placed below mid; sell orders are placed above mid.
 * This file only computes the order plan — it does not submit orders.
 */

const { roundToTick } = require("./polymarket");

// ---------------------------------------------------------------------------
// Grid level generation
// ---------------------------------------------------------------------------

/**
 * Generate an array of grid price levels centred on `mid`.
 * Levels outside (tickSize, 1-tickSize) are discarded (probabilities live in (0,1)).
 *
 * @param {number} mid           mid-price
 * @param {number} tickSize      minimum price increment, e.g. 0.01
 * @param {number} step          grid step (must be a multiple of tickSize)
 * @param {number} levelsEachSide  number of levels on each side (excluding mid)
 * @returns {number[]}  sorted ascending
 */
function makeGridLevels(mid, tickSize, step, levelsEachSide) {
  const levels = [];
  for (let i = levelsEachSide; i >= 1; i--) {
    levels.push(roundToTick(mid - step * i, tickSize));
  }
  levels.push(roundToTick(mid, tickSize));
  for (let i = 1; i <= levelsEachSide; i++) {
    levels.push(roundToTick(mid + step * i, tickSize));
  }
  // Keep only valid probabilities (exclusive boundaries)
  return levels.filter((x) => x >= tickSize && x <= 1 - tickSize);
}

// ---------------------------------------------------------------------------
// Order plan generation
// ---------------------------------------------------------------------------

/**
 * @typedef {object} OrderIntent
 * @property {"BUY"|"SELL"} side
 * @property {string}       outcome   e.g. "Up" or "Down"
 * @property {string}       tokenId
 * @property {number}       price
 * @property {number}       size
 * @property {number}       mid       mid price used to generate this level
 */

/**
 * Generate the full grid order plan for a single outcome.
 *
 * @param {object} opts
 * @param {string}  opts.outcome        outcome label, e.g. "Up"
 * @param {string}  opts.tokenId        CLOB token ID
 * @param {object}  opts.book           raw orderbook from CLOB
 * @param {number}  opts.levelsEachSide
 * @param {number}  opts.gridStep
 * @param {number}  opts.orderSize      USDC size per order
 * @returns {OrderIntent[]}
 */
function buildGridPlan({ outcome, tokenId, book, levelsEachSide, gridStep, orderSize }) {
  const tickSize = Number(book.tick_size);
  const minSize = Number(book.min_order_size);

  if (orderSize < minSize) {
    throw new Error(
      `orderSize=${orderSize} < min_order_size=${minSize} for outcome "${outcome}"`,
    );
  }
  if (Math.abs(Math.round(gridStep / tickSize) * tickSize - gridStep) > 1e-9) {
    throw new Error(
      `gridStep=${gridStep} is not a multiple of tick_size=${tickSize} for outcome "${outcome}"`,
    );
  }

  const bids = Array.isArray(book.bids) ? book.bids : [];
  const asks = Array.isArray(book.asks) ? book.asks : [];
  const bestBid = bids.length ? Number(bids[0].price) : null;
  const bestAsk = asks.length ? Number(asks[0].price) : null;

  if (bestBid === null || bestAsk === null) {
    throw new Error(`Orderbook for "${outcome}" has no bids or asks`);
  }

  const mid = (bestBid + bestAsk) / 2;
  const levels = makeGridLevels(mid, tickSize, gridStep, levelsEachSide);

  /** @type {OrderIntent[]} */
  const plan = [];
  for (const price of levels) {
    if (price < mid) {
      plan.push({ side: "BUY", outcome, tokenId, price, size: orderSize, mid });
    } else if (price > mid) {
      plan.push({ side: "SELL", outcome, tokenId, price, size: orderSize, mid });
    }
    // price === mid: skip (mid level is neutral / marker only)
  }
  return plan;
}

/**
 * Build a complete grid plan for an Up/Down market.
 *
 * @param {object} opts
 * @param {object}  opts.upBook       CLOB book for Up token
 * @param {object}  opts.downBook     CLOB book for Down token
 * @param {string}  opts.upTokenId
 * @param {string}  opts.downTokenId
 * @param {number}  opts.levelsEachSide
 * @param {number}  opts.gridStep
 * @param {number}  opts.orderSize
 * @param {boolean} opts.tradeBothOutcomes  if false, only trade Up
 * @returns {OrderIntent[]}
 */
function buildUpDownGridPlan({
  upBook,
  downBook,
  upTokenId,
  downTokenId,
  levelsEachSide,
  gridStep,
  orderSize,
  tradeBothOutcomes,
}) {
  const plan = buildGridPlan({
    outcome: "Up",
    tokenId: upTokenId,
    book: upBook,
    levelsEachSide,
    gridStep,
    orderSize,
  });

  if (tradeBothOutcomes) {
    const downPlan = buildGridPlan({
      outcome: "Down",
      tokenId: downTokenId,
      book: downBook,
      levelsEachSide,
      gridStep,
      orderSize,
    });
    plan.push(...downPlan);
  }

  // Sort: first by outcome, then by price ascending
  plan.sort((a, b) =>
    a.outcome !== b.outcome
      ? a.outcome.localeCompare(b.outcome)
      : a.price - b.price,
  );
  return plan;
}

// ---------------------------------------------------------------------------
// Signal helpers
// ---------------------------------------------------------------------------

/**
 * Calculate the percentage deviation of the current price from a reference price.
 * Positive means price is above reference.
 * @param {number} price
 * @param {number} reference
 * @returns {number}  e.g. 0.05 means +5 %
 */
function priceDeviation(price, reference) {
  if (reference === 0) return 0;
  return (price - reference) / reference;
}

module.exports = {
  makeGridLevels,
  buildGridPlan,
  buildUpDownGridPlan,
  priceDeviation,
};
