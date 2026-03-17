const https = require("https");
const zlib = require("zlib");

// ====== 你可以改的参数（先用默认） ======
const SLUG = "btc-updown-5m-1773753900";

// 网格：在 mid 上下各多少档
const LEVELS_EACH_SIDE = 5;

// 价差步长（必须是 tick_size 的整数倍；此市场 tick_size=0.01）
const GRID_STEP = 0.02;

// 每档 size（必须 >= min_order_size；此市场 min_order_size=5）
const ORDER_SIZE = 5;

// 做两边：true=Up/Down 都做；false=只做 Up
const TRADE_BOTH_OUTCOMES = true;

// ====== 工具函数 ======
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

function extractNextData(html) {
  const m = html.match(/<script[^>]+id="__NEXT_DATA__"[^>]*>([\s\S]*?)<\/script>/);
  if (!m) return null;
  return JSON.parse(m[1]);
}

function findMarketObject(nd) {
  const queries = nd?.props?.pageProps?.dehydratedState?.queries || [];
  for (const q of queries) {
    const data = q?.state?.data;
    if (data && typeof data === "object" && Array.isArray(data.markets) && data.markets[0]) {
      const mkt = data.markets[0];
      if (mkt.slug === SLUG) return mkt;
    }
  }
  return null;
}

async function getBook(tokenId) {
  const url = `https://clob.polymarket.com/book?token_id=${tokenId}`;

  // 不要用 get() 直接 buf.toString；一定要按 content-encoding 解压
  const r = await get(url, { accept: "application/json" });

  const enc = r.res.headers["content-encoding"] || "";
  const ct = r.res.headers["content-type"] || "";
  const status = r.res.statusCode;

  const text = await decompress(r.buf, enc);

  console.log("\n[book]", { tokenId, status, ct, enc, first80: text.slice(0, 80).replace(/\s+/g, " ") });

  if (status !== 200) {
    throw new Error(`book http ${status} ct=${ct} enc=${enc} bodyFirst=${text.slice(0, 120)}`);
  }

  // 有时 content-type 不是 json，但 body 是；先做个健壮判断
  const trimmed = text.trim();
  if (!trimmed.startsWith("{")) {
    throw new Error(`book not json. ct=${ct} enc=${enc} first120=${trimmed.slice(0, 120)}`);
  }

  return { status, json: JSON.parse(trimmed) };
}
function bestBidAsk(book) {
  const bid = Array.isArray(book.bids) && book.bids.length ? book.bids[0] : null; // best-first
  const ask = Array.isArray(book.asks) && book.asks.length ? book.asks[0] : null;
  return { bid, ask };
}

function roundToTick(p, tick) {
  // tick=0.01; round to nearest tick, keep 2 decimals
  const n = Math.round(p / tick) * tick;
  // avoid floating noise
  return Number(n.toFixed(String(tick).split(".")[1]?.length || 0));
}

function makeLevels(mid, tick, step, levelsEachSide) {
  const out = [];
  for (let i = levelsEachSide; i >= 1; i--) out.push(roundToTick(mid - step * i, tick));
  out.push(roundToTick(mid, tick));
  for (let i = 1; i <= levelsEachSide; i++) out.push(roundToTick(mid + step * i, tick));
  // 过滤到 [0,1]
  return out.filter((x) => x >= tick && x <= 1 - tick);
}

(async () => {
  const pageUrl = `https://polymarket.com/event/${SLUG}`;
  const r0 = await get(pageUrl, { accept: "text/html" });
  const html = await decompress(r0.buf, r0.res.headers["content-encoding"] || "");
  const nd = extractNextData(html);
  if (!nd) throw new Error("no __NEXT_DATA__ found in HTML");

  const mkt = findMarketObject(nd);
  if (!mkt) throw new Error("market object not found in dehydratedState");

  const outcomes = mkt.outcomes;
  const prices = mkt.outcomePrices;
  const tokenIds = mkt.clobTokenIds;

  console.log("market", { slug: mkt.slug, question: mkt.question, restricted: mkt.restricted });
  console.log("outcomes", outcomes);
  console.log("outcomePrices", prices);
  console.log("tokenIds", tokenIds);

  const upToken = tokenIds[0];
  const downToken = tokenIds[1];

  const [upBookR, downBookR] = await Promise.all([getBook(upToken), getBook(downToken)]);
  if (upBookR.status !== 200 || downBookR.status !== 200) throw new Error("book fetch failed");

  const upBook = upBookR.json;
  const downBook = downBookR.json;

  const tick = Number(upBook.tick_size);
  const minSize = Number(upBook.min_order_size);

  if (ORDER_SIZE < minSize) {
    throw new Error(`ORDER_SIZE=${ORDER_SIZE} < min_order_size=${minSize}`);
  }
  if (Math.round(GRID_STEP / tick) * tick !== GRID_STEP) {
    throw new Error(`GRID_STEP=${GRID_STEP} is not a multiple of tick_size=${tick}`);
  }

  const upBA = bestBidAsk(upBook);
  const downBA = bestBidAsk(downBook);

  const upMid = (Number(upBA.bid.price) + Number(upBA.ask.price)) / 2;
  const downMid = (Number(downBA.bid.price) + Number(downBA.ask.price)) / 2;

  console.log("\nUp book best:", upBA, "mid", upMid);
  console.log("Down book best:", downBA, "mid", downMid);
  console.log("tick_size", tick, "min_order_size", minSize);

  // 这里我们以 Up mid 为中心生成网格（Down 会天然互补）
  const levels = makeLevels(upMid, tick, GRID_STEP, LEVELS_EACH_SIDE);
  console.log("\ngrid levels (price):", levels);

  // 生成挂单计划：在低于 mid 的价位买入，在高于 mid 的价位卖出
  const plan = [];

  for (const p of levels) {
    if (p < upMid) plan.push({ side: "BUY", outcome: "Up", token_id: upToken, price: p, size: ORDER_SIZE });
    if (p > upMid) plan.push({ side: "SELL", outcome: "Up", token_id: upToken, price: p, size: ORDER_SIZE });
  }

  if (TRADE_BOTH_OUTCOMES) {
    // Down 的价格大约是 1 - Up（但盘口上会有 spread），我们同样按 Down mid 来生成
    const dLevels = makeLevels(downMid, tick, GRID_STEP, LEVELS_EACH_SIDE);
    for (const p of dLevels) {
      if (p < downMid) plan.push({ side: "BUY", outcome: "Down", token_id: downToken, price: p, size: ORDER_SIZE });
      if (p > downMid) plan.push({ side: "SELL", outcome: "Down", token_id: downToken, price: p, size: ORDER_SIZE });
    }
  }

  console.log("\nDRY-RUN ORDER PLAN (no orders placed):");
  plan
    .sort((a, b) => (a.outcome === b.outcome ? a.price - b.price : a.outcome.localeCompare(b.outcome)))
    .forEach((o) => console.log(o));
})();