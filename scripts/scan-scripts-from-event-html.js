const https = require("https");
const zlib = require("zlib");

const SLUG = "btc-updown-5m-1773753900";
const PAGE = `https://polymarket.com/event/${SLUG}`;
const ORIGIN = "https://polymarket.com";

const NEEDLES = [
  // hosts / keywords
  "clob.polymarket.com",
  "gamma",
  "gamma-api",
  "orderbook",
  "orderBook",
  "book?",
  "/book",
  "wss://",
  "graphql",
  "/api/",
  "/api/event/slug",
  "/api/series",

  // data fields
  "clobTokenIds",
  "conditionId",
  "token_id",
  "tokenId",
  "acceptingOrders",
  "restricted",
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

function extractScriptSrc(html) {
  const out = new Set();
  const re = /<script[^>]+src="([^"]+)"[^>]*>/g;
  let m;
  while ((m = re.exec(html))) {
    const src = m[1];
    if (src.startsWith("/_next/") && src.endsWith(".js")) out.add(src);
  }
  return [...out];
}

(async () => {
  const r0 = await get(PAGE);
  const html = await decompress(r0.buf, r0.res.headers["content-encoding"] || "");
  console.log("page status", r0.res.statusCode, "ct", r0.res.headers["content-type"]);

  const scripts = extractScriptSrc(html);
  console.log("scripts found", scripts.length);
  scripts.forEach((s, i) => console.log(String(i + 1).padStart(3), s));

  let hitFiles = 0;

  for (const s of scripts) {
    const url = ORIGIN + s;
    const r = await get(url);
    const js = await decompress(r.buf, r.res.headers["content-encoding"] || "");
    const hits = NEEDLES.filter((n) => js.includes(n));

    console.log("\nscript", s, "status", r.res.statusCode, "hits", hits.length);
    if (!hits.length) continue;

    hitFiles++;
    console.log(" needles:", hits.join(", "));

    for (const n of hits.slice(0, 6)) {
      const idx = js.indexOf(n);
      const ctx = js
        .slice(Math.max(0, idx - 140), Math.min(js.length, idx + 320))
        .replace(/\s+/g, " ");
      console.log(` context for ${n}:`, ctx);
    }
  }

  console.log("\nTOTAL HIT FILES", hitFiles);
})().catch(console.error);