const https = require("https");
const zlib = require("zlib");

const SLUG = "btc-updown-5m-1773753900";
const PAGE = `https://polymarket.com/event/${SLUG}`;
const ORIGIN = "https://polymarket.com";

const NEEDLES = [
  "clob.polymarket.com",
  "orderbook",
  "orderBook",
  "/book",
  "book?",
  "token_id",
  "tokenId",
  "clobTokenIds",
  "conditionId",
  "acceptingOrders",
  "restricted",
  "graphql",
  "wss://",
  "/api/",
  "/api/event/slug",
  "/api/series",
  "gamma",
  "gamma-api",
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

function extractNextData(html) {
  const m = html.match(/<script[^>]+id="__NEXT_DATA__"[^>]*>([\s\S]*?)<\/script>/);
  if (!m) return null;
  return JSON.parse(m[1]);
}

function normalizeSrc(src) {
  if (!src) return null;
  // scriptLoader 里可能是绝对 url 或以 /_next 开头
  if (src.startsWith("http://") || src.startsWith("https://")) return src;
  if (src.startsWith("/")) return ORIGIN + src;
  return ORIGIN + "/" + src;
}

(async () => {
  const r0 = await get(PAGE);
  const html = await decompress(r0.buf, r0.res.headers["content-encoding"] || "");
  const nd = extractNextData(html);

  if (!nd) {
    console.log("No __NEXT_DATA__ found");
    return;
  }

  console.log("buildId", nd.buildId);
  const sl = nd.scriptLoader || [];
  console.log("scriptLoader entries:", Array.isArray(sl) ? sl.length : typeof sl);

  if (!Array.isArray(sl) || sl.length === 0) {
    console.log("scriptLoader is empty. keys:", Object.keys(nd));
    return;
  }

  // 打印 scriptLoader
  sl.forEach((x, i) => {
    console.log("\n#", i + 1);
    console.log(x);
  });

  // 提取 src
  const srcs = [...new Set(sl.map((x) => x && x.src).filter(Boolean).map(normalizeSrc))];
  console.log("\nunique src count:", srcs.length);
  srcs.forEach((s, i) => console.log(String(i + 1).padStart(3), s));

  let hitFiles = 0;
  for (const u of srcs) {
    const r = await get(u);
    const js = await decompress(r.buf, r.res.headers["content-encoding"] || "");
    const hits = NEEDLES.filter((n) => js.includes(n));

    console.log("\nJS", u);
    console.log(" status", r.res.statusCode, "hits", hits.length);
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