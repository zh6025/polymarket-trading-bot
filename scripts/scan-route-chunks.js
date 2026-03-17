const https = require("https");
const zlib = require("zlib");

const BUILD_ID = "gfrbmjE5gYhrTatXYir3w";
const ORIGIN = "https://polymarket.com";
const manifestUrl = `${ORIGIN}/_next/static/${BUILD_ID}/_buildManifest.js`;

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
  "/api/",
  "/api/event/slug",
  "/api/series",
  "wss://",
  "graphql",
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

function toNextStaticUrl(p) {
  // p like "static/chunks/xxxx.js"
  if (p.startsWith("/")) p = p.slice(1);
  return `${ORIGIN}/_next/static/${BUILD_ID}/${p}`;
}

function chooseRoutes(manifest) {
  const routes = Object.keys(manifest);

  const eventRoutes = routes.filter((r) => r.includes("event"));
  if (eventRoutes.length) return eventRoutes;

  // fallback: likely used for events
  const fallback = ["/[category]/[slug]", "/[category]/[slug]/", "/[category]/[slug].json"];
  const picked = fallback.filter((r) => manifest[r]);
  if (picked.length) return picked;

  // last resort: scan the main slug route
  return ["/[category]/[slug]"].filter((r) => manifest[r]);
}

(async () => {
  console.log("manifestUrl:", manifestUrl);
  const r0 = await get(manifestUrl);
  const txt0 = await decompress(r0.buf, r0.res.headers["content-encoding"] || "");
  console.log("manifest status", r0.res.statusCode, "ct", r0.res.headers["content-type"]);
  if (r0.res.statusCode !== 200) {
    console.log("manifest first 200:", txt0.slice(0, 200));
    return;
  }

  const manifest = parseManifest(txt0);
  const routesToScan = chooseRoutes(manifest);

  console.log("routesToScan:", routesToScan);

  // collect unique chunks
  const chunkSet = new Set();
  for (const r of routesToScan) {
    const arr = manifest[r];
    if (Array.isArray(arr)) arr.forEach((c) => chunkSet.add(c));
  }
  const chunks = [...chunkSet];
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
      for (const n of hits.slice(0, 5)) {
        const idx = txt.indexOf(n);
        const context = txt
          .slice(Math.max(0, idx - 120), Math.min(txt.length, idx + 260))
          .replace(/\s+/g, " ");
        console.log(` context for ${n}:`, context);
      }
    }
  }

  console.log("\nTOTAL HIT FILES", hitFiles);
})().catch(console.error);