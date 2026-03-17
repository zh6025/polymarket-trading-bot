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

function safeGet(obj, path) {
  return path.split(".").reduce((o, k) => (o && k in o ? o[k] : undefined), obj);
}

(async () => {
  const r0 = await get(PAGE);
  const html = await decompress(r0.buf, r0.res.headers["content-encoding"] || "");
  console.log("page status", r0.res.statusCode, "ct", r0.res.headers["content-type"]);
  console.log("html len", html.length);

  const m = html.match(/<script[^>]+id="__NEXT_DATA__"[^>]*>([\s\S]*?)<\/script>/);
  if (!m) {
    console.log("NO __NEXT_DATA__ script found. first 400:", html.slice(0, 400));
    return;
  }

  const jsonText = m[1].trim();
  console.log("__NEXT_DATA__ len", jsonText.length);
  console.log("__NEXT_DATA__ first 200:", jsonText.slice(0, 200).replace(/\s+/g, " "));

  const nd = JSON.parse(jsonText);

  console.log("buildId:", nd.buildId);
  console.log("assetPrefix:", nd.assetPrefix);

  const keys = Object.keys(nd).sort();
  console.log("top-level keys:", keys);

  // 有些版本会有 files / dynamicIds / lowPriorityFiles
  console.log("has dynamicIds?", Array.isArray(nd.dynamicIds), "len", nd.dynamicIds?.length);
  console.log("has dynamicImports?", Array.isArray(nd.dynamicImports), "len", nd.dynamicImports?.length);

  // page route info
  console.log("page:", nd.page);
  console.log("query keys:", Object.keys(nd.query || {}));

  // 打印可能包含 chunk 文件名的字段（存在则打印前几个）
  const candidates = [
    "files",
    "lowPriorityFiles",
    "dynamicIds",
    "dynamicImports",
    "buildManifest",
    "runtimeConfig",
    "publicRuntimeConfig",
  ];

  for (const c of candidates) {
    const v = nd[c];
    if (v) {
      const t = Array.isArray(v) ? `array(${v.length})` : typeof v;
      console.log("candidate", c, "type", t);
      if (Array.isArray(v)) console.log(" sample:", v.slice(0, 10));
      if (typeof v === "object" && !Array.isArray(v)) console.log(" keys:", Object.keys(v).slice(0, 30));
    }
  }

  // 额外：找出 HTML 里所有 modulepreload/href 的 _next 资源
  const preload = [];
  const re = /<(link)[^>]+href="([^"]+)"[^>]*>/g;
  let mm;
  while ((mm = re.exec(html))) {
    const href = mm[2];
    if (href.includes("/_next/")) preload.push(href);
  }
  console.log("link href containing /_next/ :", preload.length);
  preload.slice(0, 40).forEach((h) => console.log(" ", h));
})();