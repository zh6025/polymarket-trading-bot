const https = require("https");
const zlib = require("zlib");

const SLUG = "btc-updown-5m-1773753900";
const PAGE = `https://polymarket.com/event/${SLUG}`;

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

function findMarket(nd) {
  const queries = nd?.props?.pageProps?.dehydratedState?.queries || [];
  for (const q of queries) {
    const data = q?.state?.data;
    if (data && typeof data === "object" && Array.isArray(data.markets) && data.markets[0]) {
      return data.markets[0];
    }
  }
  return null;
}

(async () => {
  const r0 = await get(PAGE);
  const html = await decompress(r0.buf, r0.res.headers["content-encoding"] || "");
  const nd = extractNextData(html);
  if (!nd) return console.log("no __NEXT_DATA__");

  const mkt = findMarket(nd);
  if (!mkt) return console.log("market not found in dehydratedState");

  console.log("market keys:", Object.keys(mkt).sort());

  // 把可能相关字段打印出来（存在则打印）
  const interesting = [
    "outcomes",
    "outcomePrices",
    "tokens",
    "tokenIds",
    "clobTokenIds",
    "outcome",
    "outcomeIndex",
    "yesTokenId",
    "noTokenId",
    "yesAssetId",
    "noAssetId",
    "title",
    "question",
    "slug",
  ];

  for (const k of interesting) {
    if (k in mkt) {
      console.log("\n", k, "=>");
      console.dir(mkt[k], { depth: 6 });
    }
  }
})();