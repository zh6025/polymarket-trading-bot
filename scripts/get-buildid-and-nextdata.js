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
  const { res, buf } = await get(PAGE, { accept: "text/html" });
  const html = await decompress(buf, res.headers["content-encoding"] || "");
  console.log("page status", res.statusCode, "ct", res.headers["content-type"]);

  // 从 __NEXT_DATA__ 抓 buildId
  const m = html.match(/"buildId"\s*:\s*"([^"]+)"/);
  const buildId = m ? m[1] : null;
  console.log("buildId", buildId);

  if (!buildId) {
    console.log("Could not find buildId in HTML. first 200:", html.slice(0, 200));
    return;
  }

  const nextDataUrl = `https://polymarket.com/_next/data/${buildId}/event/${SLUG}.json`;
  console.log("nextDataUrl", nextDataUrl);

  const r2 = await get(nextDataUrl, { accept: "application/json", "x-nextjs-data": "1", referer: PAGE });
  const txt2 = await decompress(r2.buf, r2.res.headers["content-encoding"] || "");
  console.log("next-data status", r2.res.statusCode, "ct", r2.res.headers["content-type"]);
  console.log("next-data first 200:", txt2.slice(0, 200).replace(/\s+/g, " "));

  const j = JSON.parse(txt2);
  const qs = j?.pageProps?.dehydratedState?.queries || [];
  console.log("queries", qs.length);

  const keys = [...new Set(qs.map((q) => JSON.stringify(q.queryKey)).filter(Boolean))].sort();
  console.log("queryKeys:");
  for (const k of keys) console.log(k);

  // 粗略找出任何包含 clobTokenIds/conditionId 的片段
  const raw = JSON.stringify(j);
  console.log("contains clobTokenIds?", raw.includes("clobTokenIds"));
  console.log("contains conditionId?", raw.includes("conditionId"));
})();