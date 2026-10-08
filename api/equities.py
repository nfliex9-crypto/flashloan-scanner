from __future__ import annotations
import json
from http.server import BaseHTTPRequestHandler
from aegis.equity_data import get_equity_quotes
from aegis.priority_markets import priority_market_board

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            body=get_equity_quotes()
            body['priority_markets']=priority_market_board()['markets']
            status=200 if body.get("ok") else 502
        except Exception as exc:
            body={"ok":False,"error":str(exc),"live_execution_enabled":False}
            status=500
        payload=json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Cache-Control","public, s-maxage=30, stale-while-revalidate=30")
        self.end_headers()
        self.wfile.write(payload)
