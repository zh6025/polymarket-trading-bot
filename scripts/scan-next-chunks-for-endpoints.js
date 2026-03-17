const https = require("https");
const zlib = require("zlib");

const BUILD_ID = "wwZkodzWGW9waMJPUhj-Q";
const ORIGIN = "https://polymarket.com";

const manifestUrl = `${ORIGIN}/_next/static/${BUILD_ID}/_buildManifest.js`;

// 这些词用于定位“客户端真正请求数据”的地方
const NEEDLES = [
  "clob.polymarket.com",
  "polymarket.com/api/",
  "/api/event/slug",
  "/api/market",
  "/api/markets",
  "orderbook",
  "getOrderBook",
  "token_id",
  "clobTokenIds",
  "conditionId",
  "enableOrderBook",
  "acceptingOrders",
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

function extractJsPathsFromManifestText(txt) {
  // _buildManifest.js looks like: self.__BUILD_MANIFEST = {...}; self.__BUILD_MANIFEST_CB && self.__BUILD_MANIFEST_CB();
  // We'll just regex out .js paths
  const re = /"([^"]+?\.js)"/g;
  const out = new Set();
  let m;
  while ((m = re.exec(txt))) {
    const p = m[1];
    if (p.startsWith("/_next/")) out.add(p);
  }
  return [...out];
}

async function main() {
  console.log("Fetching manifest:", manifestUrl);
  const r0 = await get(manifestUrl);
  const txt0 = await decompress(r0.buf, r0.res.headers["content-encoding"] || "");
  console.log("manifest status", r0.res.statusCode, "ct", r0.res.headers["content-type"]);
  const jsPaths = extractJsPathsFromManifestText(txt0);
  console.log("JS paths in manifest:", jsPaths.length);

  // 限制一下数量避免太慢：优先扫含有 "event"、"market"、"clob" 的 chunk
  const prioritized = jsPaths
    .map((p) => ({ p, score: NEEDLES.reduce((s, n) => (p.includes(n.split("/")[0]) ? s + 1 : s), 0) }))
    .sort((a, b) => b.score - a.score)
    .map((x) => x.p);

  // 也加上 framework/main 这类核心文件
  const top = prioritized.slice(0, Math.min(120, prioritized.length));

  console.log("Scanning JS files:", top.length);

  let totalHits = 0;
  for (let i = 0; i < top.length; i++) {
    const path = top[i];
    const url = ORIGIN + path;
    const r = await get(url);
    const txt = await decompress(r.buf, r.res.headers["content-encoding"] || "");
    const hits = [];
    for (const n of NEEDLES) {
      if (txt.includes(n)) hits.push(n);
    }
    if (hits.length) {
      totalHits += 1;
      console.log("\nHIT", totalHits, "file", path);
      console.log(" needles:", hits.join(", "));
      // 打印一小段上下文，方便你我定位
      for (const n of hits.slice(0, 3)) {
        const idx = txt.indexOf(n);
        const start = Math.max(0, idx - 80);
        const end = Math.min(txt.length, idx + 200);
        console.log(` context for ${n}:`, txt.slice(start, end).replace(/\s+/g, " "));
      }
    }
  }

  console.log("\nTOTAL HIT FILES:", totalHits);
}

main().catch(console.error);