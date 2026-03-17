const https = require("https");
const zlib = require("zlib");

const URL = "https://polymarket.com/zh/event/btc-updown-5m-1773584100";

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
  const { res, buf } = await get(URL);
  const html = await decompress(buf, res.headers["content-encoding"] || "");
  const re = /\/_next\/static\/chunks\/[^"' ]+\.js/g;
  const m = html.match(re) || [];
  const uniq = [...new Set(m)].sort();
  console.log("chunks", uniq.length);
  for (const x of uniq) console.log("https://polymarket.com" + x);
})();