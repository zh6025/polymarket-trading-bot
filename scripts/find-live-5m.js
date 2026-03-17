const https = require("https");
const zlib = require("zlib");

const SERIES_SLUG = "btc-up-or-down-5m";
const URL = "https://polymarket.com/zh/event/btc-updown-5m-1773584100";

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

function deepCollectMarkets(node, out = []) {
  if (!node || typeof node !== "object") return out;
  if (Array.isArray(node)) {
    for (const x of node) deepCollectMarkets(x, out);
    return out;
  }
  // heuristic: market-ish object
  if (
    typeof node.slug === "string" &&
    typeof node.question === "string" &&
    (node.conditionId || node.questionID || node.clobTokenIds)
  ) {
    out.push(node);
  }
  for (const v of Object.values(node)) deepCollectMarkets(v, out);
  return out;
}

https
  .get(
    URL,
    { headers: { "user-agent": "Mozilla/5.0", "accept-encoding": "gzip, deflate, br" } },
    (res) => {
      const chunks = [];
      res.on("data", (c) => chunks.push(c));
      res.on("end", async () => {
        const buf = Buffer.concat(chunks);
        const html = await decompress(buf, res.headers["content-encoding"] || "");

        const re = /<script[^>]*id="__NEXT_DATA__"[^>]*>([\s\S]*?)<\/script>/;
        const m = html.match(re);
        if (!m) throw new Error("NO __NEXT_DATA__");
        const nextData = JSON.parse(m[1]);

        const allMarkets = deepCollectMarkets(nextData);
        const inSeries = allMarkets.filter((mk) => {
          const seriesSlug =
            mk?.series?.slug ||
            mk?.series?.[0]?.slug ||
            mk?.events?.[0]?.series?.[0]?.slug;
          return seriesSlug === SERIES_SLUG;
        });

        const normalized = inSeries.map((mk) => ({
          slug: mk.slug,
          question: mk.question,
          conditionId: mk.conditionId,
          clobTokenIds: mk.clobTokenIds,
          active: mk.active,
          closed: mk.closed,
          acceptingOrders: mk.acceptingOrders,
          startDate: mk.startDate,
          endDate: mk.endDate,
          updatedAt: mk.updatedAt,
          restricted: mk.restricted,
          ready: mk.ready,
          funded: mk.funded,
        }));

        normalized.sort((a, b) => String(b.startDate || "").localeCompare(String(a.startDate || "")));

        const candidates = normalized.filter((x) => x.closed === false || x.acceptingOrders === true || x.active === true);
        console.log("Found markets in series:", normalized.length);
        console.log("Top 10 (most recent by startDate):");
        console.log(JSON.stringify(normalized.slice(0, 10), null, 2));
        console.log("\nCandidates (active/acceptingOrders/not closed):");
        console.log(JSON.stringify(candidates.slice(0, 20), null, 2));
      });
    },
  )
  .on("error", (e) => console.error(e));