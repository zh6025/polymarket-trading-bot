lib/polymarket.js
v2
const { getText, getJson } = require("./http");

function extractNextDataFromHtml(html) {
  const m = html.match(/<script[^>]+id="__NEXT_DATA__"[^>]*>([\s\S]*?)<\/script>/);
  if (!m) return null;
  return JSON.parse(m[1]);
