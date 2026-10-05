from __future__ import annotations

import json
from decimal import Decimal
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from opportunity_finder import find_opportunities


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            params = parse_qs(urlparse(self.path).query)
            size = Decimal(params.get("size", ["1000"])[0])

            if size < Decimal("10") or size > Decimal("250000"):
                raise ValueError("size must be between 10 and 250,000 USDC")

            body = find_opportunities(size)
            status = 200
        except Exception as exc:
            body = {"ok": False, "error": str(exc)}
            status = 500

        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)
