"""Polymarket CLOB API endpoint constants."""

CLOB_BASE_URL = "https://clob.polymarket.com"
GAMMA_BASE_URL = "https://gamma-api.polymarket.com"

# CLOB endpoints
CLOB_MARKETS = "/markets"
CLOB_BOOK = "/book"
CLOB_ORDER = "/order"
CLOB_ORDERS = "/orders"
CLOB_FILLS = "/data/fills"
CLOB_BALANCE = "/balance-allowance"
CLOB_TICK_SIZE = "/tick-size"
CLOB_MIDPOINT = "/midpoint"
CLOB_SPREAD = "/spread"
CLOB_PRICE = "/price"

# Gamma endpoints
GAMMA_MARKETS = "/markets"
GAMMA_EVENTS = "/events"

# Chainlink BTC/USD feed on Polygon (used by Polymarket for resolution)
CHAINLINK_BTC_USD_POLYGON = "0xc907E116054Ad103354f2D350FD2514433D57F6f"

# Binance WebSocket
BINANCE_WS_BASE = "wss://stream.binance.com:9443/ws"
BINANCE_REST_BASE = "https://api.binance.com"
BINANCE_KLINES = "/api/v3/klines"
BINANCE_PRICE = "/api/v3/ticker/price"
