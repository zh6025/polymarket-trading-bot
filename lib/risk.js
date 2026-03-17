"use strict";

/**
 * lib/risk.js
 * Risk management and position control.
 *
 * Tracks daily PnL, open positions, and implements a circuit breaker that
 * halts new order placement when limits are breached.
 */

const { log } = require("./utils");

// ---------------------------------------------------------------------------
// RiskManager class
// ---------------------------------------------------------------------------

class RiskManager {
  /**
   * @param {object} opts
   * @param {number} opts.maxDailyLossUsdc  circuit breaker: stop if daily loss exceeds this
   * @param {number} opts.maxPositionUsdc   maximum total open position value in USDC
   */
  constructor({ maxDailyLossUsdc = 50, maxPositionUsdc = 200 } = {}) {
    this.maxDailyLossUsdc = maxDailyLossUsdc;
    this.maxPositionUsdc = maxPositionUsdc;

    /** Realised PnL for the current calendar day (USDC) */
    this.dailyPnl = 0;

    /** Map of tokenId → open position size */
    this._positions = new Map();

    /** Day stamp (YYYY-MM-DD) for daily reset */
    this._today = _dateStamp();

    /** True when the circuit breaker has been tripped */
    this.halted = false;
  }

  // ── Daily reset ───────────────────────────────────────────────────────────

  /**
   * Reset daily counters if the calendar date has rolled over.
   */
  _maybeDailyReset() {
    const today = _dateStamp();
    if (today !== this._today) {
      log.info(`RiskManager: daily reset (${this._today} → ${today})`);
      this.dailyPnl = 0;
      this.halted = false;
      this._today = today;
    }
  }

  // ── Position tracking ─────────────────────────────────────────────────────

  /**
   * Record a fill.
   * @param {object} fill
   * @param {"BUY"|"SELL"} fill.side
   * @param {string}       fill.tokenId
   * @param {number}       fill.size    amount in shares
   * @param {number}       fill.price   fill price (0-1)
   */
  recordFill({ side, tokenId, size, price }) {
    this._maybeDailyReset();
    const current = this._positions.get(tokenId) || 0;
    if (side === "BUY") {
      this._positions.set(tokenId, current + size);
      this.dailyPnl -= size * price; // cash out
    } else {
      this._positions.set(tokenId, current - size);
      this.dailyPnl += size * price; // cash in
    }
    this._checkCircuitBreaker();
  }

  /**
   * Record a settled outcome (market resolves).
   * @param {string} tokenId
   * @param {number} payoutPerShare  1 if outcome won, 0 if lost
   */
  recordSettlement(tokenId, payoutPerShare) {
    const pos = this._positions.get(tokenId) || 0;
    this.dailyPnl += pos * payoutPerShare;
    this._positions.set(tokenId, 0);
    this._checkCircuitBreaker();
  }

  // ── Limit checks ─────────────────────────────────────────────────────────

  /**
   * Compute total open position value (sum of |position| × assumed price 0.5 as placeholder).
   * @returns {number}
   */
  totalOpenPositionUsdc() {
    let total = 0;
    for (const size of this._positions.values()) {
      total += Math.abs(size) * 0.5; // rough USDC estimate at 0.5 mid
    }
    return total;
  }

  /**
   * Check whether a proposed order is allowed.
   * @param {object} order
   * @param {number} order.size
   * @param {number} order.price
   * @returns {{ allowed: boolean, reason: string|null }}
   */
  checkOrder({ size, price }) {
    this._maybeDailyReset();
    if (this.halted) {
      return { allowed: false, reason: "circuit breaker is tripped" };
    }
    const orderValue = size * price;
    const projected = this.totalOpenPositionUsdc() + orderValue;
    if (projected > this.maxPositionUsdc) {
      return {
        allowed: false,
        reason: `position limit: projected ${projected.toFixed(2)} > max ${this.maxPositionUsdc}`,
      };
    }
    return { allowed: true, reason: null };
  }

  // ── Circuit breaker ───────────────────────────────────────────────────────

  _checkCircuitBreaker() {
    if (!this.halted && this.dailyPnl < -this.maxDailyLossUsdc) {
      this.halted = true;
      log.warn(
        `RiskManager: CIRCUIT BREAKER TRIPPED — daily PnL ${this.dailyPnl.toFixed(2)} < -${this.maxDailyLossUsdc}`,
      );
    }
  }

  /**
   * Manually reset the circuit breaker (e.g. at start of new session).
   */
  resetCircuitBreaker() {
    this.halted = false;
    log.info("RiskManager: circuit breaker manually reset");
  }

  // ── Status ────────────────────────────────────────────────────────────────

  /** @returns {object} snapshot of current risk state */
  status() {
    return {
      date: this._today,
      dailyPnl: Number(this.dailyPnl.toFixed(4)),
      totalOpenPositionUsdc: Number(this.totalOpenPositionUsdc().toFixed(4)),
      halted: this.halted,
      positions: Object.fromEntries(this._positions),
    };
  }
}

// ---------------------------------------------------------------------------
// Internals
// ---------------------------------------------------------------------------

/** @returns {string} e.g. "2025-01-15" */
function _dateStamp() {
  return new Date().toISOString().slice(0, 10);
}

module.exports = { RiskManager };
