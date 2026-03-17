"use strict";

/**
 * lib/polymarket.js
 * Polymarket API client — markets, orderbook, CLOB helpers.
 */

const { getText, getJson, decompress, get } = require("./utils");

const POLYMARKET_ORIGIN = "https://polymarket.com";
const CLOB_ORIGIN = "https://clob.polymarket.com";

// ---------------------------------------------------------------------------
// HTML / __NEXT_DATA__ helpers
// ---------------------------------------------------------------------------

/**
 * Extract and parse the `__NEXT_DATA__` JSON embedded in a Polymarket HTML page.
 * @param {string} html
 * @returns {object|null}
 */
function extractNextDataFromHtml(html) {
  const m = html.match(/<script[^>]+id="__NEXT_DATA__"[^>]*>([\s\S]*?)<\/script>/);
  if (!m) return null;
  return JSON.parse(m[1]);
}

/**
 * Find the market object matching `slug` inside dehydratedState queries.
 * @param {object} nextData  parsed __NEXT_DATA__
 * @param {string} slug
 * @returns {object|null}
 */
function findMarketInNextData(nextData, slug) {
  const queries = nextData?.props?.pageProps?.dehydratedState?.queries || [];
  for (const q of queries) {
    const data = q?.state?.data;
    if (data && typeof data === "object" && Array.isArray(data.markets)) {
      for (const mkt of data.markets) {
        if (mkt && mkt.slug === slug) return mkt;
      }
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// Market discovery via REST API
// ---------------------------------------------------------------------------

/**
 * Fetch the series object (including all events) for a given series slug.
 * @param {string} seriesSlug  e.g. "btc-up-or-down-5m"
 * @returns {Promise<object>}
 */
async function fetchSeries(seriesSlug) {
  const url = `${POLYMARKET_ORIGIN}/api/series?slug=${encodeURIComponent(seriesSlug)}`;
  return getJson(url, { "x-nextjs-data": "1" });
}

/**
 * Fetch event details (including markets) by event slug.
 * @param {string} eventSlug  e.g. "btc-updown-5m-1773753900"
 * @returns {Promise<object>}
 */
async function fetchEventBySlug(eventSlug) {
  const url = `${POLYMARKET_ORIGIN}/api/event/slug?slug=${encodeURIComponent(eventSlug)}`;
  return getJson(url, { "x-nextjs-data": "1" });
}

/**
 * Find the most recently opened event in the series that is still open.
 * Returns null if no open event is found.
 * @param {string} seriesSlug
 * @returns {Promise<object|null>}
 */
async function findLatestOpenEvent(seriesSlug) {
  const series = await fetchSeries(seriesSlug);
  const events = Array.isArray(series.events) ? series.events : [];
  const open = events.filter((e) => e && e.closed === false);
  if (!open.length) return null;
  open.sort((a, b) => {
    const endDiff = _toTime(b.endDate) - _toTime(a.endDate);
    return endDiff !== 0 ? endDiff : _toTime(b.startDate) - _toTime(a.startDate);
  });
  return open[0];
}

/**
 * Return tradable markets (acceptingOrders=true, active=true, closed=false) for an event slug.
 * @param {string} eventSlug
 * @returns {Promise<object[]>}
 */
async function fetchTradableMarkets(eventSlug) {
  const event = await fetchEventBySlug(eventSlug);
  const markets = Array.isArray(event.markets) ? event.markets : [];
  return markets.filter((m) => m && m.acceptingOrders === true && m.closed === false && m.active === true);
}

// ---------------------------------------------------------------------------
// Market data from event HTML page
// ---------------------------------------------------------------------------

/**
 * Fetch the event HTML page and extract the market object matching `slug`
 * from embedded __NEXT_DATA__.
 * @param {string} slug  event slug
 * @returns {Promise<object>}
 */
async function fetchMarketFromEventPage(slug) {
  const pageUrl = `${POLYMARKET_ORIGIN}/event/${slug}`;
  const html = await getText(pageUrl, { accept: "text/html" });
  const nextData = extractNextDataFromHtml(html);
  if (!nextData) throw new Error(`No __NEXT_DATA__ found on page: ${pageUrl}`);
  const mkt = findMarketInNextData(nextData, slug);
  if (!mkt) throw new Error(`Market "${slug}" not found in __NEXT_DATA__ dehydratedState`);
  return mkt;
}

/**
 * Build a mapping of outcome name → token ID from a market object.
 * For a typical Up/Down market returns { Up: "...", Down: "..." }.
 * @param {object} market
 * @returns {Record<string, string>}
 */
function getUpDownMappingFromMarket(market) {
  const outcomes = market.outcomes || [];
  const tokenIds = market.clobTokenIds || [];
  const mapping = {};
  for (let i = 0; i < outcomes.length; i++) {
    if (tokenIds[i]) mapping[outcomes[i]] = tokenIds[i];
  }
  return mapping;
}

// ---------------------------------------------------------------------------
// CLOB orderbook
// ---------------------------------------------------------------------------

/**
 * Fetch the CLOB orderbook for a token.
 * @param {string} tokenId
 * @returns {Promise<object>}  raw book JSON { bids, asks, tick_size, min_order_size, ... }
 */
async function fetchBook(tokenId) {
  const url = `${CLOB_ORIGIN}/book?token_id=${tokenId}`;
  const { res, buf } = await get(url, { accept: "application/json" });
  const enc = res.headers["content-encoding"] || "";
  const text = await decompress(buf, enc);

  if (res.statusCode !== 200) {
    throw new Error(`CLOB book HTTP ${res.statusCode} for token ${tokenId}: ${text.slice(0, 200)}`);
  }
  const trimmed = text.trim();
  if (!trimmed.startsWith("{")) {
    throw new Error(`CLOB book response is not JSON for token ${tokenId}: ${trimmed.slice(0, 120)}`);
  }
  return JSON.parse(trimmed);
}

/**
 * Extract best bid and best ask from a book object.
 * Polymarket returns bids in descending order and asks in ascending order,
 * so the best bid is bids[0] and best ask is asks[0].
 * @param {object} book
 * @returns {{ bid: {price:string,size:string}|null, ask: {price:string,size:string}|null }}
 */
function bestBidAsk(book) {
  const bid = Array.isArray(book.bids) && book.bids.length ? book.bids[0] : null;
  const ask = Array.isArray(book.asks) && book.asks.length ? book.asks[0] : null;
  return { bid, ask };
}

/**
 * Calculate mid price from best bid and ask.
 * Returns null if either side is missing.
 * @param {object} book
 * @returns {number|null}
 */
function calcMid(book) {
  const { bid, ask } = bestBidAsk(book);
  if (!bid || !ask) return null;
  return (Number(bid.price) + Number(ask.price)) / 2;
}

/**
 * Fetch orderbooks for both Up and Down tokens simultaneously.
 * @param {string} upTokenId
 * @param {string} downTokenId
 * @returns {Promise<{upBook: object, downBook: object}>}
 */
async function fetchBothBooks(upTokenId, downTokenId) {
  const [upBook, downBook] = await Promise.all([fetchBook(upTokenId), fetchBook(downTokenId)]);
  return { upBook, downBook };
}

// ---------------------------------------------------------------------------
// Price rounding
// ---------------------------------------------------------------------------

/**
 * Round `price` to the nearest multiple of `tickSize`.
 * @param {number} price
 * @param {number} tickSize  e.g. 0.01
 * @returns {number}
 */
function roundToTick(price, tickSize) {
  const decimals = (String(tickSize).split(".")[1] || "").length;
  const n = Math.round(price / tickSize) * tickSize;
  return Number(n.toFixed(decimals));
}

// ---------------------------------------------------------------------------
// Internals
// ---------------------------------------------------------------------------

function _toTime(x) {
  if (x == null) return -1;
  const t = typeof x === "number" ? x : Date.parse(x);
  return Number.isFinite(t) ? t : -1;
}

module.exports = {
  // HTML helpers
  extractNextDataFromHtml,
  findMarketInNextData,
  // Market discovery
  fetchSeries,
  fetchEventBySlug,
  findLatestOpenEvent,
  fetchTradableMarkets,
  // Page scraping
  fetchMarketFromEventPage,
  getUpDownMappingFromMarket,
  // CLOB orderbook
  fetchBook,
  bestBidAsk,
  calcMid,
  fetchBothBooks,
  // Price helpers
  roundToTick,
};
