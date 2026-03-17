const https = require("https");
const zlib = require("zlib");

const url = "https://polymarket.com/zh/event/btc-updown-5m-1773584100";

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
  url,
  { headers: { "user-agent": "Mozilla/5.0", "accept-encoding": "gzip, deflate, br" } },
  (res) => {
    const chunks = [];
    res.on("data", (c) => chunks.push(c));
    res.on("end", async () => {
      const buf = Buffer.concat(chunks);
      const enc = res.headers["content-encoding"] || "";
      const html = await decompress(buf, enc);

      console.log("status", res.statusCode, "len", html.length, "encoding", enc || "none");

      const re = /<script[^>]*id="__NEXT_DATA__"[^>]*>([\s\S]*?)<\/script>/;
      const m = html.match(re);
      if (!m) return console.log("NO __NEXT_DATA__");

      const jsonText = m[1];
      console.log("__NEXT_DATA__ chars", jsonText.length);

      const keys = ["clobtokenids", "clob", "token_id", "condition_id", "market_slug", "question_id", "graphql"];
      const lower = jsonText.toLowerCase();

      for (const key of keys) {
        const idx = lower.indexOf(key);
        console.log("has " + key + "?", idx >= 0);
        if (idx >= 0) {
          console.log("---- around " + key + " ----");
          const before = key === "clobtokenids" ? 2000 : 250;
const after = key === "clobtokenids" ? 4000 : 500;
console.log(jsonText.slice(Math.max(0, idx - before), idx + after));
        }
      }
    });
  }
).on("error", (e) => console.error("ERR", e));