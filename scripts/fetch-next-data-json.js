const https = require("https");
const zlib = require("zlib");

const PAGE = "https://polymarket.com/zh/event/btc-updown-5m-1773584100";

function get(url) {
  return new Promise((resolve, reject) => {
    https
      .get(
        url,
        {
          headers: {
            "user-agent": "Mozilla/5.0",
            "accept-encoding": "gzip, deflate, br",
            accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
          },
        },
        (res) => {
          const chunks = [];
          res.on("data", (c) => chunks.push(c));
          res.on("end", () => resolve({ res, buf: Buffer.concat(chunks) }));
        },
      )
      .on("error", reject);
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
  // 1) fetch HTML
  const { res: res1, buf: buf1 } = await get(PAGE);
  const html = await decompress(buf1, res1.headers["content-encoding"] || "");
  console.log("HTML status", res1.statusCode, "len", html.length);

  const m = html.match(/<script[^>]*id="__NEXT_DATA__"[^>]*>([\s\S]*?)<\/script>/);
  if (!m) throw new Error("NO __NEXT_DATA__ in HTML");

  const nextData = JSON.parse(m[1]);
  const buildId = nextData.buildId;
  console.log("buildId", buildId);

  // 2) fetch Next.js data JSON
  const dataUrl = `https://polymarket.com/_next/data/${buildId}/zh/event/btc-updown-5m-1773584100.json`;
  const { res: res2, buf: buf2 } = await get(dataUrl);
  const txt = await decompress(buf2, res2.headers["content-encoding"] || "");
  console.log("DATA status", res2.statusCode, "len", txt.length);
  console.log("DATA first chars:", txt.slice(0, 120));

  // 3) quick search in data json
  const lower = txt.toLowerCase();
  for (const key of ["series", "10684", "btc-up-or-down-5m", "markets", "acceptingorders", "clobtokenids"]) {
    console.log("has", key, "?", lower.includes(key.toLowerCase()));
  }
})();