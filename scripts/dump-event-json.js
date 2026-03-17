const https = require("https");
const zlib = require("zlib");

const SLUG = "btc-updown-5m-1773753900";
const URL = `https://polymarket.com/api/event/slug?slug=${encodeURIComponent(SLUG)}`;

function get(url) {
  return new Promise((resolve, reject) => {
    https.get(
      url,
      {
        headers: {
          "user-agent": "Mozilla/5.0",
          accept: "application/json",
          "x-nextjs-data": "1",
          // 模拟浏览器导航来源，有时会影响权限/裁剪
          referer: `https://polymarket.com/zh/event/${SLUG}`,
        },
      },
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

(async () => {
  const { res, buf } = await get(URL);
  const txt = await decompress(buf, res.headers["content-encoding"] || "");
  console.log("status", res.statusCode, "ct", res.headers["content-type"]);
  console.log("raw first 600 chars:\n", txt.slice(0, 600));

  const j = JSON.parse(txt);
  console.log("\nTop-level keys:", Object.keys(j));
  console.log("\nmarkets length:", Array.isArray(j.markets) ? j.markets.length : "(no markets field)");

  // 深度找任何包含 "conditionId"/"clobTokenIds" 的对象数量
  const hits = [];
  const seen = new Set();
  function walk(x, path = "$") {
    if (!x || typeof x !== "object") return;
    if (seen.has(x)) return;
    seen.add(x);
    if (x.conditionId || x.clobTokenIds) hits.push(path);
    if (Array.isArray(x)) {
      for (let i = 0; i < x.length; i++) walk(x[i], `${path}[${i}]`);
    } else {
      for (const [k, v] of Object.entries(x)) walk(v, `${path}.${k}`);
    }
  }
  walk(j);
  console.log("\nPaths containing conditionId or clobTokenIds (first 50):");
  console.log(hits.slice(0, 50));
})();