const https = require("https");
const zlib = require("zlib");

const buildId = "wwZkodzWGW9waMJPUhj-Q";
const url = `https://polymarket.com/_next/data/${buildId}/zh/event/btc-updown-5m-1773584100.json`;

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

(async () => {
  const { res, buf } = await get(url);
  const txt = await decompress(buf, res.headers["content-encoding"] || "");
  const json = JSON.parse(txt);

  const qs = json?.pageProps?.dehydratedState?.queries || [];
  console.log("queries", qs.length);

  // 打印所有 queryKey（去重）
  const keys = [];
  for (const q of qs) {
    const k = q?.queryKey;
    if (k) keys.push(JSON.stringify(k));
  }
  const uniq = [...new Set(keys)].sort();
  console.log("unique queryKeys", uniq.length);
  for (const k of uniq) console.log(k);
})();
