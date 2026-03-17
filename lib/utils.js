"use strict";

const https = require("https");
const zlib = require("zlib");

const _agent = new https.Agent({ keepAlive: true });

/**
 * HTTP GET — returns { res, buf }
 * @param {string} url
 * @param {object} [extraHeaders]
 * @returns {Promise<{res: import('http').IncomingMessage, buf: Buffer}>}
 */
function get(url, extraHeaders = {}) {
  return new Promise((resolve, reject) => {
    https
      .get(
        url,
        {
          agent: _agent,
          headers: {
            "user-agent": "Mozilla/5.0",
            "accept-encoding": "gzip, deflate, br",
            ...extraHeaders,
          },
        },
        (res) => {
          const chunks = [];
          res.on("data", (c) => chunks.push(c));
          res.on("end", () => resolve({ res, buf: Buffer.concat(chunks) }));
        },
      )
      .on("error", reject);
  });
}

/**
 * HTTP GET — decodes body as JSON
 * @param {string} url
 * @param {object} [extraHeaders]
 * @returns {Promise<any>}
 */
async function getJson(url, extraHeaders = {}) {
  const { res, buf } = await get(url, { accept: "application/json", ...extraHeaders });
  const text = await decompress(buf, res.headers["content-encoding"] || "");
  if (res.statusCode !== 200) {
    throw new Error(`HTTP ${res.statusCode} from ${url}: ${text.slice(0, 200)}`);
  }
  return JSON.parse(text);
}

/**
 * HTTP GET — decodes body as text (HTML etc.)
 * @param {string} url
 * @param {object} [extraHeaders]
 * @returns {Promise<string>}
 */
async function getText(url, extraHeaders = {}) {
  const { res, buf } = await get(url, extraHeaders);
  const text = await decompress(buf, res.headers["content-encoding"] || "");
  if (res.statusCode !== 200) {
    throw new Error(`HTTP ${res.statusCode} from ${url}: ${text.slice(0, 200)}`);
  }
  return text;
}

/**
 * Decompress a buffer according to the Content-Encoding header value.
 * Falls back to returning the raw buffer as UTF-8 on decompression error.
 * @param {Buffer} buf
 * @param {string} encoding  e.g. "gzip", "br", "deflate", ""
 * @returns {Promise<string>}
 */
function decompress(buf, encoding) {
  encoding = (encoding || "").toLowerCase();
  return new Promise((resolve) => {
    const done = (out) => resolve(out.toString("utf8"));
    if (encoding === "gzip") return zlib.gunzip(buf, (e, out) => done(e ? buf : out));
    if (encoding === "br") return zlib.brotliDecompress(buf, (e, out) => done(e ? buf : out));
    if (encoding === "deflate") return zlib.inflate(buf, (e, out) => done(e ? buf : out));
    return done(buf);
  });
}

/**
 * Sleep for `ms` milliseconds.
 * @param {number} ms
 * @returns {Promise<void>}
 */
function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

/**
 * Parse a date string or timestamp to a Unix epoch number.
 * Returns -1 if unparseable.
 * @param {string|number|undefined} x
 * @returns {number}
 */
function toTime(x) {
  if (x == null) return -1;
  const t = typeof x === "number" ? x : Date.parse(x);
  return Number.isFinite(t) ? t : -1;
}

/**
 * Return ISO timestamp string for now, e.g. "2025-01-15T08:30:00.000Z"
 * @returns {string}
 */
function nowIso() {
  return new Date().toISOString();
}

/**
 * Simple levelled logger.  All output goes to stdout/stderr.
 */
const log = {
  /** @param {...any} args */
  info(...args) {
    console.log(`[${nowIso()}] INFO`, ...args);
  },
  /** @param {...any} args */
  warn(...args) {
    console.warn(`[${nowIso()}] WARN`, ...args);
  },
  /** @param {...any} args */
  error(...args) {
    console.error(`[${nowIso()}] ERROR`, ...args);
  },
  /** @param {...any} args */
  debug(...args) {
    if (process.env.DEBUG) console.log(`[${nowIso()}] DEBUG`, ...args);
  },
};

module.exports = { get, getJson, getText, decompress, sleep, toTime, nowIso, log };
