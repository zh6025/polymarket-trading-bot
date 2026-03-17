const https = require("https");

const TOKENS = [
  "45970400659669226816001866880557654806809487717270707458890512468006552340712",
  "111877298808301746779637883585506416913816190115550002660843920005782401504338",
];

function getJson(url) {
  return new Promise((resolve, reject) => {
    https.get(
      url,
      { headers: { "user-agent": "Mozilla/5.0", accept: "application/json" } },
      (res) => {
        const chunks = [];
        res.on("data", (c) => chunks.push(c));
        res.on("end", () => {
          const body = Buffer.concat(chunks).toString("utf8");
          resolve({ status: res.statusCode, json: body ? JSON.parse(body) : null });
        });
      },
    ).on("error", reject);
  });
}

function bestOf(arr, side) {
  if (!Array.isArray(arr) || arr.length === 0) return null;
  // Polymarket book is sorted best-first already, but we’ll be safe
  const sorted = [...arr].sort((a, b) => (side === "bid" ? Number(b.price) - Number(a.price) : Number(a.price) - Number(b.price)));
  return sorted[0];
}

(async () => {
  for (const t of TOKENS) {
    const url = `https://clob.polymarket.com/book?token_id=${t}`;
    const { status, json } = await getJson(url);
    console.log("\nTOKEN", t);
    console.log("status", status);
    if (status !== 200) continue;

    const bid = bestOf(json.bids, "bid");
    const ask = bestOf(json.asks, "ask");

    const bidP = bid ? Number(bid.price) : null;
    const askP = ask ? Number(ask.price) : null;
    const mid = bidP != null && askP != null ? (bidP + askP) / 2 : null;

    console.log("market(conditionId)", json.market);
    console.log("tick_size", json.tick_size, "min_order_size", json.min_order_size);
    console.log("bestBid", bid, "bestAsk", ask);
    console.log("mid", mid, "last_trade_price", json.last_trade_price);
  }
})();