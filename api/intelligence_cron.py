from __future__ import annotations

import hmac
import json
import os
from http.server import BaseHTTPRequestHandler
from aegis.intelligence_ledger import collect_intelligence

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        expected=os.getenv("CRON_SECRET","")
        bearer=self.headers.get("Authorization","")
        if not expected or not hmac.compare_digest(bearer, f"Bearer {expected}"):
            self._reply(401,{"ok":False,"error":"unauthorized"})
            return
        try:
            self._reply(200,collect_intelligence())
        except Exception as exc:
            self._reply(500,{"ok":False,"error":str(exc)})

    def _reply(self,status: int,data: dict):
        payload=json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Cache-Control","no-store")
        self.end_headers()
        self.wfile.write(payload)
