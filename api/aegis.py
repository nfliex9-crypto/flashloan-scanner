from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler

from aegis.live_lab import build_live_floor


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            body = build_live_floor()
            status = 200
        except Exception as exc:
            body = {"ok": False, "error": str(exc)}
            status = 500

        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "public, s-maxage=20, stale-while-revalidate=120")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)
