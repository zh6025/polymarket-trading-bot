const https = require("https");
const zlib = require("zlib");

const URL = "https://polymarket.com/zh/event/btc-updown-5m-1773584100";
const patterns = [
  /https?:\/\/[^"'\\\s]+/g,
  /\/[a-zA-Z0-9_\-\/]*api[a-zA-Z0-9_\-\/]*/g,
  /graphql[^"'\\\s]*/gi,
  /clob[^"'\\\s]*/gi,
];

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

https.get(
  URL,
  { headers: { "user-agent": "Mozilla/5.0", "accept-encoding": "gzip, deflate, br" } },
  (res) => {
    const chunks = [];
    res.on("data", (c) => chunks.push(c));
    res.on("end", async () => {
      const html = await decompress(Buffer.concat(chunks), res.headers["content-encoding"] || "");

      const hits = new Set();
      for (const re of patterns) {
        const m = html.match(re) || [];
        for (const x of m) {
          if (/polymarket|pm-|clob|graphql|api/i.test(x)) hits.add(x);
        }
      }

      const arr = [...hits].sort();
      console.log("hits", arr.length);
      for (const x of arr.slice(0, 400)) console.log(x); // cap
    });
  }
).on("error", (e) => console.error(e));