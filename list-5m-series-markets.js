const https = require("https");
const zlib = require("zlib");

const buildId = "wwZkodzWGW9waMJPUhj-Q";
const dataUrl = `https://polymarket.com/_next/data/${buildId}/zh/event/btc-updown-5m-1773584100.json`;

const SERIES_ID = "10684";
const SERIES_SLUG = "btc-up-or-down-5m";

function get(url) {
  return new Promise((resolve, reject) => {
    https
      .get(
        url,
        {
          headers: {
            "user-agent": "Mozilla/5.0",
            "accept-encoding": "gzip, deflate, br",
            accept: "application/json,text/plain,*/*",
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

function collectMarkets(node, out = []) {
  if (!node || typeof node !== "object") return out;
  if (Array.isArray(node)) {
    for (const x of node) collectMarkets(x, out);
    return out;
  }
  // market-ish: has slug+question and either conditionId or clobTokenIds
  if (typeof node.slug === "string" && typeof node.question === "string" && (node.conditionId || node.clobTokenIds)) {
    out.push(node);
  }
  for (const v of Object.values(node)) collectMarkets(v, out);
  return out;
}

function getSeriesInfo(mk) {
  // series might be object or array
  if (mk?.series?.id || mk?.series?.slug) return mk.series;
  if (Array.isArray(mk?.series) && mk.series[0]) return mk.series[0];
  if (Array.isArray(mk?.events) && mk.events[0]?.series?.[0]) return mk.events[0].series[0];
  return null;
}

(async () => {
  const { res, buf } = await get(dataUrl);
  const txt = await decompress(buf, res.headers["content-encoding"] || "");
  console.log("DATA status", res.statusCode, "len", txt.length);

  const json = JSON.parse(txt);
  const all = collectMarkets(json);
  console.log("all market-like objects found:", all.length);

  const inSeries = all.filter((mk) => {
    const s = getSeriesInfo(mk);
    const sid = s?.id != null ? String(s.id) : null;
    const sslug = s?.slug;
    return sid === SERIES_ID || sslug === SERIES_SLUG;
  });

  const normalized = inSeries.map((mk) => {
    const s = getSeriesInfo(mk);
    return {
      id: mk.id != null ? String(mk.id) : null,
      slug: mk.slug,
      question: mk.question,
      seriesId: s?.id != null ? String(s.id) : null,
      seriesSlug: s?.slug || null,
      startDate: mk.startDate || mk.eventStartTime || mk.start_time || null,
      endDate: mk.endDate || mk.end_date || null,
      active: mk.active,
      closed: mk.closed,
      restricted: mk.restricted,
      acceptingOrders: mk.acceptingOrders,
      ready: mk.ready,
      funded: mk.funded,
      conditionId: mk.conditionId || null,
      clobTokenIds: mk.clobTokenIds || null,
      updatedAt: mk.updatedAt || mk.updated_at || null,
    };
  });

  normalized.sort((a, b) => String(b.startDate || b.updatedAt || "").localeCompare(String(a.startDate || a.updatedAt || "")));

  const candidates = normalized.filter((x) => x.acceptingOrders === true && x.closed === false && x.active === true);

  console.log("\nMost recent 20 markets in series:");
  console.log(JSON.stringify(normalized.slice(0, 20), null, 2));

  console.log("\nCandidates (acceptingOrders=true, active=true, closed=false):");
  console.log(JSON.stringify(candidates.slice(0, 20), null, 2));
})();