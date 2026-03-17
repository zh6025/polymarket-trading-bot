const https = require("https");
const zlib = require("zlib");

const SLUG = "btc-updown-5m-1773753900";
const URL = `https://polymarket.com/api/event/slug?slug=${encodeURIComponent(SLUG)}`;

function get(url, headers) {
  return new Promise((resolve, reject) => {
    https.get(url, { headers }, (res) => {
      const chunks = [];
      res.on("data", (c) => chunks.push(c));
      res.on("end", () => resolve({ res, buf: Buffer.concat(chunks) }));
    }).on("error", reject);
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
  const variants = [
    { name: "plain", headers: { "user-agent": "Mozilla/5.0", accept: "*/*" } },
    { name: "json", headers: { "user-agent": "Mozilla/5.0", accept: "application/json" } },
    {
      name: "next-data",
      headers: {
        "user-agent": "Mozilla/5.0",
        accept: "application/json",
        "x-nextjs-data": "1",
        referer: `https://polymarket.com/event/${SLUG}`,
      },
    },
  ];

  for (const v of variants) {
    const { res, buf } = await get(URL, v.headers);
    const txt = await decompress(buf, res.headers["content-encoding"] || "");
    console.log("\n===", v.name, "===");
    console.log("status", res.statusCode);
    console.log("content-type", res.headers["content-type"]);
    console.log("first", txt.slice(0, 200).replace(/\s+/g, " "));
  }
})().catch(console.error);