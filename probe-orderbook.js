const https = require("https");

const TOKEN_ID = "45970400659669226816001866880557654806809487717270707458890512468006552340712";

const CANDIDATES = [
  // 常见组合（不同版本/网关）
  { url: `https://clob.polymarket.com/book?token_id=${TOKEN_ID}` },
  { url: `https://clob.polymarket.com/book?tokenId=${TOKEN_ID}` },
  { url: `https://clob.polymarket.com/orderbook?token_id=${TOKEN_ID}` },
  { url: `https://clob.polymarket.com/orderbook?tokenId=${TOKEN_ID}` },
  { url: `https://clob.polymarket.com/market/${TOKEN_ID}/book` },
  { url: `https://clob.polymarket.com/markets/${TOKEN_ID}/book` },

  // 有些网关用 /books/{tokenId}
  { url: `https://clob.polymarket.com/books/${TOKEN_ID}` },

  // 有些用 data-api 子域
  { url: `https://data-api.polymarket.com/book?token_id=${TOKEN_ID}` },
  { url: `https://data-api.polymarket.com/orderbook?token_id=${TOKEN_ID}` },
];

function get(url) {
  return new Promise((resolve, reject) => {
    https.get(
      url,
      {
        headers: {
          "user-agent": "Mozilla/5.0",
          accept: "application/json",
        },
      },
      (res) => {
        const chunks = [];
        res.on("data", (c) => chunks.push(c));
        res.on("end", () =>
          resolve({
            status: res.statusCode,
            ct: res.headers["content-type"],
            body: Buffer.concat(chunks).toString("utf8"),
          }),
        );
      },
    ).on("error", reject);
  });
}

(async () => {
  for (const c of CANDIDATES) {
    try {
      const r = await get(c.url);
      const first = r.body.slice(0, 200).replace(/\s+/g, " ");
      console.log("\nURL:", c.url);
      console.log("status", r.status, "ct", r.ct);
      console.log("first", first);

      if (r.status === 200 && r.ct && r.ct.includes("application/json") && r.body.trim().startsWith("{")) {
        const j = JSON.parse(r.body);
        // 尝试输出 best bid/ask（字段名不确定，尽量兼容）
        const bids = j.bids || j.buy || j.bid || j.data?.bids;
        const asks = j.asks || j.sell || j.ask || j.data?.asks;
        if (bids || asks) {
          console.log("parsed keys:", Object.keys(j));
          console.log("bids sample:", Array.isArray(bids) ? bids.slice(0, 3) : bids);
          console.log("asks sample:", Array.isArray(asks) ? asks.slice(0, 3) : asks);
        }
      }
    } catch (e) {
      console.log("\nURL:", c.url);
      console.log("ERR", e.message);
    }
  }
})();
