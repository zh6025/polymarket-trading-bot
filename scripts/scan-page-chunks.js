const https = require("https");
const zlib = require("zlib");

const PAGE = "https://polymarket.com/zh/event/btc-updown-5m-1773584100";

const needles = [
  "/api/series",
  "api/series",
  "/api/event/slug",
  "event/slug",
  "series?id",
  "seriesId",
  "cursor",
  "offset",
  "limit",
  "page",
  "acceptingOrders",
  "clobTokenIds",
  "btc-up-or-down-5m",
  "10684",
];

function get(url) {
  return new Promise((resolve, reject) => {
    https.get(
      url,
      {
        headers: {
          "user-agent": "Mozilla/5.0",
          "accept-encoding": "gzip, deflate, br",
          accept: "*/*",
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

function extractChunks(html) {
  const re = /\/_next\/static\/chunks\/[^"' ]+\.js/g;
  const m = html.match(re) || [];
  return [...new Set(m)].map((p) => "https://polymarket.com" + p).sort();
}

function around(txt, idx, n = 250) {
  return txt.slice(Math.max(0, idx - n), Math.min(txt.length, idx + n));
}

(async () => {
  const { res: r1, buf: b1 } = await get(PAGE);
  const html = await decompress(b1, r1.headers["content-encoding"] || "");
  const chunks = extractChunks(html);

  console.log("HTML", r1.statusCode, "chunks", chunks.length);

  let hitCount = 0;

  // 扫前 60 个 chunk（通常足够命中请求封装）
  for (const url of chunks.slice(0, 60)) {
    let txt = "";
    try {
      const { res, buf } = await get(url);
      if (res.statusCode !== 200) continue;
      // js chunks 通常不压缩；即便压缩，这里也当 utf8 读（足够做 includes）
      txt = buf.toString("utf8");
    } catch {
      continue;
    }

    const hits = needles.filter((n) => txt.includes(n));
    if (!hits.length) continue;

    hitCount++;
    console.log("\n=== HIT", hitCount, url, "===");
    console.log("needles:", hits.join(", "));

    // 每个 needle 打印一段上下文（截断避免太长）
    for (const n of hits.slice(0, 6)) {
      const idx = txt.indexOf(n);
      console.log("\n--- around:", n, "---");
      console.log(around(txt, idx, 350));
    }
  }

  console.log("\nTOTAL HIT CHUNKS:", hitCount);
})();
