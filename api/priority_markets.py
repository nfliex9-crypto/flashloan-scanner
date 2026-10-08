from http.server import BaseHTTPRequestHandler
import json
from aegis.priority_markets import priority_market_board

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            result=priority_market_board()
            status=200
        except Exception as e:
            result={"ok":False,"error":str(e),"live_money":False}
            status=503
        raw=json.dumps(result).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Cache-Control","no-store")
        self.end_headers()
        self.wfile.write(raw)
