const https = require("https");
const zlib = require("zlib");

const SERIES_SLUG = "btc-up-or-down-5m";

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

function toTime(x) {
  const t = Date.parse(x || "");
  return Number.isFinite(t) ? t : -1;
}

(async () => {
  // 1) fetch series with all events
  const seriesUrl = `https://polymarket.com/api/series?slug=${encodeURIComponent(SERIES_SLUG)}`;
  const r1 = await get(seriesUrl);
  const txt1 = await decompress(r1.buf, r1.res.headers["content-encoding"] || "");
  const series = JSON.parse(txt1);

  const events = Array.isArray(series.events) ? series.events : [];
  console.log("series", series.id, series.slug, "events", events.length);

  // 2) pick most recent OPEN event (closed=false), prefer highest endDate then startDate
  const open = events.filter((e) => e && e.closed === false);
  open.sort((a, b) => (toTime(b.endDate) - toTime(a.endDate)) || (toTime(b.startDate) - toTime(a.startDate)));

  const chosen = open[0];
  if (!chosen) {
    console.log("No open events found in series.");
    return;
  }

  console.log("\nChosen open event:");
  console.log({
    id: chosen.id,
    slug: chosen.slug,
    title: chosen.title,
    startDate: chosen.startDate,
    endDate: chosen.endDate,
    updatedAt: chosen.updatedAt,
    restricted: chosen.restricted,
    active: chosen.active,
    closed: chosen.closed,
  });

  // 3) fetch event details -> markets
  const eventUrl = `https://polymarket.com/api/event/slug?slug=${encodeURIComponent(chosen.slug)}`;
  const r2 = await get(eventUrl);
  const txt2 = await decompress(r2.buf, r2.res.headers["content-encoding"] || "");
  const event = JSON.parse(txt2);

  const markets = Array.isArray(event.markets) ? event.markets : [];
  console.log("\nEvent markets:", markets.length);

  // 4) find tradable markets
  const tradable = markets.filter((m) => m && m.acceptingOrders === true && m.closed === false && m.active === true);

  console.log("\nTradable markets (acceptingOrders=true, active=true, closed=false):");
  console.log(
    JSON.stringify(
      tradable.map((m) => ({
        id: m.id,
        slug: m.slug,
        question: m.question,
        conditionId: m.conditionId,
        restricted: m.restricted,
        acceptingOrders: m.acceptingOrders,
        ready: m.ready,
        funded: m.funded,
        clobTokenIds: m.clobTokenIds,
        orderMinSize: m.orderMinSize,
        orderPriceMinTickSize: m.orderPriceMinTickSize,
      })),
      null,
      2,
    ),
  );

  // also print first market for debugging if none
  if (!tradable.length && markets[0]) {
    const m0 = markets[0];
    console.log("\nNo tradable market found; first market looks like:");
    console.log({
      id: m0.id,
      slug: m0.slug,
      closed: m0.closed,
      active: m0.active,
      acceptingOrders: m0.acceptingOrders,
      restricted: m0.restricted,
      ready: m0.ready,
      funded: m0.funded,
      clobTokenIds: m0.clobTokenIds,
    });
  }
})().catch((e) => console.error(e?.response?.data || e));