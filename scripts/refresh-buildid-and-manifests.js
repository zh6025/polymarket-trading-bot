const https = require("https");
const zlib = require("zlib");

const SLUG = "btc-updown-5m-1773753900";
const PAGE = `https://polymarket.com/event/${SLUG}`;

function get(url, headers = {}) {
  return new Promise((resolve, reject) => {
    https.get(
      url,
      {
        headers: {
          "user-agent": "Mozilla/5.0",
          "accept-encoding": "gzip, deflate, br",
          ...headers,
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
  const r0 = await get(PAGE, { accept: "text/html" });
  const html = await decompress(r0.buf, r0.res.headers["content-encoding"] || "");
  console.log("page status", r0.res.statusCode, "ct", r0.res.headers["content-type"]);

  const m = html.match(/"buildId"\s*:\s*"([^"]+)"/);
  const buildId = m ? m[1] : null;
  console.log("buildId", buildId);

  if (!buildId) {
    console.log("Could not find buildId. html first 300:", html.slice(0, 300));
    return;
  }

  const urls = [
    `https://polymarket.com/_next/static/${buildId}/_buildManifest.js`,
    `https://polymarket.com/_next/static/${buildId}/_ssgManifest.js`,
  ];

  for (const u of urls) {
    const r = await get(u, { accept: "*/*", referer: PAGE });
    const txt = await decompress(r.buf, r.res.headers["content-encoding"] || "");
    console.log("\n", u);
    console.log(" status", r.res.statusCode, "ct", r.res.headers["content-type"]);
    console.log(" first200", txt.slice(0, 200).replace(/\s+/g, " "));
  }
})();