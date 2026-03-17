const https = require("https");
const zlib = require("zlib");

const BUILD_ID = "wwZkodzWGW9waMJPUhj-Q";
const ORIGIN = "https://polymarket.com";
const manifestUrl = `${ORIGIN}/_next/static/${BUILD_ID}/_buildManifest.js`;

const ROUTES_TO_TRY = [
  "/event/[slug]",
  "/zh/event/[slug]",
  "/[category]/[slug]",     // 有些站把 event 放这里
  "/zh/[category]/[slug]",
];

const NEEDLES = [
  "clob.polymarket.com",
  "orderbook",
  "book?",
  "/book",
  "token_id",
  "tokenId",
  "clobTokenIds",
  "conditionId",
  "acceptingOrders",
  "enableOrderBook",
  "/api/",
  "/api/event/slug",
  "/api/series",
  "ws://",
  "wss://",
];

function get(url) {
  return new Promise((resolve, reject) => {
    https.get(
      url,
      { headers: { "user-agent": "Mozilla/5.0", "accept-encoding": "gzip, deflate, br" } },
      (res) => {
        const chunks = [];
        res.on("data", (c) => chunks.push(c));
        res.on("end", () => resolve({ res, buf: Buffer.concat(chunks) }));
      },
    ).on("error", reject);
  });
}

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

function parseManifest(txt) {
  // _buildManifest.js is JS code: self.__BUILD_MANIFEST = {...}
  // We'll extract the {...} and JSON.parse after making it JSON-safe.
  const start = txt.indexOf("{");
  const end = txt.lastIndexOf("}");
  const objText = txt.slice(start, end + 1);

  // Manifest object is JSON-compatible (keys quoted, values arrays of strings).
  // But it might have trailing commas; remove them conservatively.
  const jsonLike = objText.replace(/,\s*([}\]])/g, "$1");
  return JSON.parse(jsonLike);
}

function toNextStaticUrl(p) {
  // p like "static/chunks/xxxx.js"
  if (p.startsWith("/")) p = p.slice(1);
  return `${ORIGIN}/_next/static/${BUILD_ID}/${p}`;
}

(async () => {
  const r0 = await get(manifestUrl);
  const txt0 = await decompress(r0.buf, r0.res.headers["content-encoding"] || "");
  console.log("manifest status", r0.res.statusCode, "ct", r0.res.headers["content-type"]);

  const manifest = parseManifest(txt0);

  let route = null;
  let chunks = null;
  for (const r of ROUTES_TO_TRY) {
    if (manifest[r]) {
      route = r;
      chunks = manifest[r];
      break;
    }
  }

  console.log("matched route:", route);
  if (!chunks) {
    console.log("No matching route found. Available keys sample:", Object.keys(manifest).slice(0, 30));
    return;
  }

  console.log("chunks:", chunks);

  let hitFiles = 0;
  for (const c of chunks) {
    const url = toNextStaticUrl(c);
    const r = await get(url);
    const txt = await decompress(r.buf, r.res.headers["content-encoding"] || "");
    const hits = NEEDLES.filter((n) => txt.includes(n));

    console.log("\nfile", c, "status", r.res.statusCode, "hits", hits.length);
    if (hits.length) {
      hitFiles++;
      console.log(" needles:", hits.join(", "));
      for (const n of hits.slice(0, 3)) {
        const idx = txt.indexOf(n);
        console.log(` context for ${n}:`, txt.slice(Math.max(0, idx - 80), Math.min(txt.length, idx + 220)).replace(/\s+/g, " "));
      }
    }
  }

  console.log("\nTOTAL HIT FILES", hitFiles);
})().catch(console.error);