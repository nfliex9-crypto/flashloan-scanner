from __future__ import annotations

import json
import urllib.request
from http.server import BaseHTTPRequestHandler


STATE_URL = (
    "https://raw.githubusercontent.com/"
    "nfliex9-crypto/flashloan-scanner/"
    "paper-state/data/paper_state.json"
)


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            request = urllib.request.Request(
                STATE_URL,
                headers={"User-Agent": "AEGIS-Dashboard/2.0"},
            )
            with urllib.request.urlopen(request, timeout=6) as response:
                body = json.loads(response.read().decode("utf-8"))
            body["ok"] = True
            status = 200
        except Exception as exc:
            body = {
                "ok": True,
                "initialized": False,
                "message": "Forward paper ledger is initializing.",
                "detail": str(exc)[:180],
            }
            status = 200

        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header(
            "Cache-Control",
            "public, s-maxage=45, stale-while-revalidate=180",
        )
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)
