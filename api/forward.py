from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler

from aegis.forward_broker import get_forward_state


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            body = get_forward_state()
            status = 200
        except Exception as exc:
            body = {"ok": False, "error": str(exc)}
            status = 500

        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)
