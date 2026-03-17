const https = require("https");
const zlib = require("zlib");

const SLUG = "btc-updown-5m-1773753900";
const PAGE = `https://polymarket.com/event/${SLUG}`;

function get(url) {
  return new Promise((resolve, reject) => {
    https.get(
      url,
      { headers: { "user-agent": "Mozilla/5.0", "accept-encoding": "gzip, deflate, br" } },
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

// 深度遍历，找到包含某些 key 的对象，打印路径和一个简短摘要
function walk(obj, onNode, path = "$", seen = new Set()) {
  if (obj && typeof obj === "object") {
    if (seen.has(obj)) return;
    seen.add(obj);
    onNode(obj, path);
    if (Array.isArray(obj)) {
      obj.forEach((v, i) => walk(v, onNode, `${path}[${i}]`, seen));
    } else {
      for (const [k, v] of Object.entries(obj)) {
        walk(v, onNode, `${path}.${k}`, seen);
      }
    }
  }
}

function pick(obj, keys) {
  const out = {};
  for (const k of keys) if (k in obj) out[k] = obj[k];
  return out;
}

(async () => {
  const r0 = await get(PAGE);
  const html = await decompress(r0.buf, r0.res.headers["content-encoding"] || "");
  console.log("page status", r0.res.statusCode);

  const nd = extractNextData(html);
  if (!nd) {
    console.log("no __NEXT_DATA__");
    return;
  }

  const raw = JSON.stringify(nd);
  console.log("buildId", nd.buildId);
  console.log("contains clobTokenIds?", raw.includes("clobTokenIds"));
  console.log("contains conditionId?", raw.includes("conditionId"));
  console.log("contains token_id?", raw.includes("token_id"));
  console.log("contains orderbook?", raw.toLowerCase().includes("orderbook"));
  console.log("contains restricted?", raw.includes("restricted"));

  const hits = [];
  walk(nd, (node, p) => {
    if (!node || typeof node !== "object" || Array.isArray(node)) return;

    const keys = Object.keys(node);
    if (
      keys.includes("clobTokenIds") ||
      keys.includes("conditionId") ||
      keys.includes("token_id") ||
      keys.includes("tokenId") ||
      keys.includes("acceptingOrders")
    ) {
      hits.push({ path: p, sample: pick(node, ["id","slug","title","question","acceptingOrders","closed","restricted","conditionId","clobTokenIds","token_id","tokenId"]) });
    }
  });

  console.log("nodes with target keys:", hits.length);
  hits.slice(0, 30).forEach((h, i) => {
    console.log("\nHIT", i + 1, h.path);
    console.log(h.sample);
  });

  // 同时把 dehydrated queries 的 queryKey 打印出来（用于定位调用来源）
  const queries = nd?.props?.pageProps?.dehydratedState?.queries || [];
  console.log("\ndehydrated queries:", queries.length);
  const keys = queries.map((q) => JSON.stringify(q.queryKey)).filter(Boolean);
  const uniq = [...new Set(keys)].sort();
  console.log("unique queryKeys:", uniq.length);
  uniq.slice(0, 80).forEach((k) => console.log(k));
})();