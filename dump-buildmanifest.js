const https = require("https");
const zlib = require("zlib");

const BUILD_ID = "wwZkodzWGW9waMJPUhj-Q";
const URL = `https://polymarket.com/_next/static/${BUILD_ID}/_buildManifest.js`;

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
  const txt = await decompress(buf, res.headers["content-encoding"] || "");
  console.log("status", res.statusCode, "ct", res.headers["content-type"]);
  console.log("len", txt.length);
  console.log("first400:\n", txt.slice(0, 400));
})();