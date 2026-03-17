const https = require("https");
const zlib = require("zlib");

const BUILD_ID = "gfrbmjE5gYhrTatXYir3w";
const ORIGIN = "https://polymarket.com";
const manifestUrl = `${ORIGIN}/_next/static/${BUILD_ID}/_buildManifest.js`;

const NEEDLES = [
  // hosts
  "clob.polymarket.com",
  "gamma-api",
  "polymarket.com/api",
  "graph",
  "graphql",
  "wss://",

  // endpoints / fields
  "orderbook",
  "orderBook",
  "book?",
  "/book",
  "token_id",
  "tokenId",
  "clobTokenIds",
  "conditionId",
  "acceptingOrders",
  "restricted",
  "market",
  "markets",
  "/api/",
  "/api/event/slug",
  "/api/series",
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
  const start = txt.indexOf("{");
  const end = txt.lastIndexOf("}");
  const objText = txt.slice(start, end + 1);
  const jsonLike = objText.replace(/,\s*([}\]])/g, "$1");
  return JSON.parse(jsonLike);
}

function chooseRoutes(manifest) {
  const routes = Object.keys(manifest);
  const eventRoutes = routes.filter((r) => r.includes("event"));
  // 优先只扫事件页和 usapp 事件页，避免扫 sitemap
  const filtered = eventRoutes.filter((r) => r.includes("/event/") || r.includes("usapp/event"));
  return filtered.length ? filtered : eventRoutes;
}

function chunkUrl(p) {
  // p like "static/chunks/xxxx.js" -> "/_next/static/chunks/xxxx.js"
  const rel = p.startsWith("static/") ? p.slice("static/".length) : p;
  return `${ORIGIN}/_next/static/${rel}`;
}

function findHits(txt) {
  const hits = [];
  for (const n of NEEDLES) if (txt.includes(n)) hits.push(n);
  return hits;
}

(async () => {
  console.log("manifestUrl:", manifestUrl);
  const r0 = await get(manifestUrl);
  const txt0 = await decompress(r0.buf, r0.res.headers["content-encoding"] || "");
  console.log("manifest status", r0.res.statusCode);
  if (r0.res.statusCode !== 200) {
    console.log("manifest first 200:", txt0.slice(0, 200));
    return;
  }

  const manifest = parseManifest(txt0);
  const routesToScan = chooseRoutes(manifest);
  console.log("routesToScan:", routesToScan);

  const chunkSet = new Set();
  for (const r of routesToScan) {
    const arr = manifest[r];
    if (Array.isArray(arr)) arr.forEach((c) => chunkSet.add(c));
  }
  const chunks = [...chunkSet];
  console.log("chunks:", chunks);

  let hitFiles = 0;
  for (const c of chunks) {
    const url = chunkUrl(c);
    const r = await get(url);
    const body = await decompress(r.buf, r.res.headers["content-encoding"] || "");

    console.log("\nchunk", c, "status", r.res.statusCode);
    if (r.res.statusCode !== 200) continue;

    const hits = findHits(body);
    console.log(" hits", hits.length);
    if (!hits.length) continue;

    hitFiles++;
    console.log(" needles:", hits.join(", "));

    // 打印前几个命中词的上下文
    for (const n of hits.slice(0, 6)) {
      const idx = body.indexOf(n);
      const ctx = body
        .slice(Math.max(0, idx - 140), Math.min(body.length, idx + 320))
        .replace(/\s+/g, " ");
      console.log(` context for ${n}:`, ctx);
    }
  }

  console.log("\nTOTAL HIT FILES", hitFiles);
})().catch(console.error);