from __future__ import annotations
import json
from http.server import BaseHTTPRequestHandler
from aegis.stage3 import get_stage3_state

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            payload = get_stage3_state()
            status = 200
        except Exception as exc:
            payload = {"ok":False,"error":str(exc)}
            status = 500
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Cache-Control","no-store")
        self.end_headers()
        self.wfile.write(raw)
