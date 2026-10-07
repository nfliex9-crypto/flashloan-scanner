from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler

from aegis.forward_broker import run_forward_tick


class handler(BaseHTTPRequestHandler):
    def _reply(self, status: int, body: dict):
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        secret = os.getenv("PAPER_TICK_SECRET")
        auth = self.headers.get("Authorization", "")
        if not secret or auth != f"Bearer {secret}":
            self._reply(401, {"ok": False, "error": "unauthorized"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            data = json.loads(raw.decode("utf-8") or "{}")
            scheduled = data.get("scheduled_at")
            if scheduled:
                scheduled_at = datetime.fromisoformat(str(scheduled).replace("Z", "+00:00"))
                if scheduled_at.tzinfo is None:
                    scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)
            else:
                scheduled_at = datetime.now(timezone.utc)

            body = run_forward_tick(scheduled_at=scheduled_at)
            self._reply(200, body)
        except Exception as exc:
            self._reply(500, {"ok": False, "error": str(exc)})

    def do_GET(self):
        self._reply(405, {"ok": False, "error": "POST only"})
