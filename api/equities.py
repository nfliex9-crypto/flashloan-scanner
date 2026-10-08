from __future__ import annotations
import json
from http.server import BaseHTTPRequestHandler
from aegis.equity_data import get_equity_quotes
from aegis.priority_markets import priority_market_board

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            # BTC and gold remain available even if the lower-priority stock feed fails.
            gold_and_crypto = priority_market_board()["markets"]
            try:
                body = get_equity_quotes()
            except Exception:
                body = {"ok": False, "connected": False, "mode": "EQUITY_FEED_ERROR",
                        "stocks": [], "live_execution_enabled": False}
            body["priority_markets"] = gold_and_crypto
            status = 200
        except Exception as exc:
            body={"ok":False,"error":"market_data_temporarily_unavailable","live_execution_enabled":False}
            status=500
        payload=json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Cache-Control","public, s-maxage=600, stale-while-revalidate=300")
        self.end_headers()
        self.wfile.write(payload)
