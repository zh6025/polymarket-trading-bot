const https = require("https");
const zlib = require("zlib");

function get(url) {
  return new Promise((resolve, reject) => {
    https.get(
      url,
      {
        headers: {
          "user-agent": "Mozilla/5.0",
          accept: "application/json",
          "x-nextjs-data": "1",
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
  const base = "https://polymarket.com/api/series?slug=btc-up-or-down-5m";
  const urls = [
    base,
    base + "&limit=50",
    base + "&page=1&limit=50",
    base + "&offset=0&limit=50",
    base + "&cursor=",
  ];

  for (const u of urls) {
    const { res, buf } = await get(u);
    const txt = await decompress(buf, res.headers["content-encoding"] || "");
    let info = "";

    try {
      const j = JSON.parse(txt);
      const ev = j.events || [];
      const open = ev.filter((e) => e && e.closed === false).length;
      info = `events=${ev.length} open=${open} updatedAt=${j.updatedAt || ""}`;
      if (ev[0]) info += ` firstEvent=${ev[0].slug || ev[0].ticker || ""} closed=${ev[0].closed}`;
    } catch {
      info = txt.slice(0, 120).replace(/\s+/g, " ");
    }

    console.log("\nURL:", u);
    console.log("status", res.statusCode, "ct", res.headers["content-type"]);
    console.log(info);
  }
})().catch((e) => console.error(e));