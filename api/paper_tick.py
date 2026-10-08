from __future__ import annotations

import hmac
import json
import os
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler

from aegis.forward_broker import run_forward_tick


MAX_REQUEST_BYTES = 4096
MAX_SCHEDULE_DRIFT_SECONDS = 7200


def validate_scheduled_at(value: str | None, *, now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    scheduled = datetime.fromisoformat(value.replace("Z", "+00:00")) if value else now
    if scheduled.tzinfo is None:
        raise ValueError("scheduled_at must include a timezone")
    scheduled = scheduled.astimezone(timezone.utc)
    if abs((now - scheduled).total_seconds()) > MAX_SCHEDULE_DRIFT_SECONDS:
        raise ValueError("scheduled_at outside the allowed 2-hour window")
    return scheduled


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
        if not secret or not hmac.compare_digest(auth, f"Bearer {secret}"):
            self._reply(401, {"ok": False, "error": "unauthorized"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length < 0 or length > MAX_REQUEST_BYTES:
                self._reply(413, {"ok": False, "error": "request_too_large"})
                return
            raw = self.rfile.read(length) if length else b"{}"
            data = json.loads(raw.decode("utf-8") or "{}")
            if not isinstance(data, dict):
                raise ValueError("scheduler body must be a JSON object")
            scheduled_at = validate_scheduled_at(data.get("scheduled_at"))
            body = run_forward_tick(scheduled_at=scheduled_at)
            self._reply(200, body)
        except (ValueError, TypeError, json.JSONDecodeError):
            self._reply(400, {"ok": False, "error": "invalid_scheduler_payload"})
        except Exception:
            # Database/provider exception strings can contain connection data.
            # Do not return them from a public API.
            self._reply(503, {"ok": False, "error": "paper_tick_temporarily_unavailable"})

    def do_GET(self):
        self._reply(405, {"ok": False, "error": "POST only"})
