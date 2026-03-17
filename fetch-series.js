const https = require("https");
const zlib = require("zlib");

const SERIES_SLUG = "btc-up-or-down-5m";
const URL = `https://polymarket.com/api/series?slug=${encodeURIComponent(SERIES_SLUG)}`;

function get(url) {
  return new Promise((resolve, reject) => {
    https
      .get(
        url,
        {
          headers: {
            "user-agent": "Mozilla/5.0",
            accept: "application/json, text/plain, */*",
            // 关键：让它像 Next 的数据请求
            "x-nextjs-data": "1",
            referer: `https://polymarket.com/zh/predictions/up-or-down`,
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
  const { res, buf } = await get(URL);
  const txt = await decompress(buf, res.headers["content-encoding"] || "");
  console.log("status", res.statusCode);
  console.log("content-type", res.headers["content-type"]);
  console.log("first", txt.slice(0, 200));

  // 如果是 JSON，就解析并打印 keys，找 markets 列表/分页
  try {
    const j = JSON.parse(txt);
    console.log("JSON keys:", Object.keys(j));
    // 常见返回：{ series: {...}, markets: [...]} 或 { data: ... }
    console.log(JSON.stringify(j, null, 2).slice(0, 4000));
  } catch (e) {
    console.log("NOT JSON");
  }
})();
