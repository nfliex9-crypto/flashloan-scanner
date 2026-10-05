from __future__ import annotations

import hmac
import json
import os
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from aegis.alpaca_paper import (
    PAPER_BASE_URL,
    account,
    is_configured,
    orders,
    place_market_order,
    positions,
)


def authorized(headers) -> bool:
    required = os.getenv("AEGIS_CONTROL_TOKEN", "").strip()
    if not required:
        return False
    supplied = headers.get("X-Aegis-Control-Token", "").strip()
    return hmac.compare_digest(required, supplied)


def send(handler, status: int, body: dict) -> None:
    payload = json.dumps(body).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type, X-Aegis-Control-Token")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.end_headers()
    handler.wfile.write(payload)


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        send(self, 200, {"ok": True})

    def do_GET(self):
        configured = is_configured()
        if not configured:
            send(
                self,
                200,
                {
                    "ok": True,
                    "configured": False,
                    "connected": False,
                    "broker": "Alpaca Paper Trading",
                    "endpoint": PAPER_BASE_URL,
                    "live_money": False,
                    "message": "Paper broker credentials are not configured yet.",
                },
            )
            return

        if not authorized(self.headers):
            send(
                self,
                200,
                {
                    "ok": True,
                    "configured": True,
                    "connected": False,
                    "locked": True,
                    "broker": "Alpaca Paper Trading",
                    "endpoint": PAPER_BASE_URL,
                    "live_money": False,
                    "message": "Broker is configured but this dashboard session is locked.",
                },
            )
            return

        try:
            send(
                self,
                200,
                {
                    "ok": True,
                    "configured": True,
                    "connected": True,
                    "locked": False,
                    "broker": "Alpaca Paper Trading",
                    "endpoint": PAPER_BASE_URL,
                    "live_money": False,
                    "account": account(),
                    "positions": positions(),
                    "orders": orders(15),
                    "max_order_usd": float(
                        os.getenv("AEGIS_PAPER_MAX_ORDER_USD", "1000")
                    ),
                },
            )
        except Exception as exc:
            send(
                self,
                502,
                {
                    "ok": False,
                    "configured": True,
                    "connected": False,
                    "error": str(exc)[:240],
                },
            )

    def do_POST(self):
        if not is_configured():
            send(self, 409, {"ok": False, "error": "paper broker is not configured"})
            return

        if not authorized(self.headers):
            send(self, 401, {"ok": False, "error": "control token required"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            body = json.loads(raw)

            action = body.get("action")
            if action != "place_market_order":
                raise ValueError("unsupported action")

            order = place_market_order(
                symbol=str(body.get("symbol", "")),
                side=str(body.get("side", "")),
                notional_usd=float(body.get("notional_usd", 0)),
            )

            send(
                self,
                200,
                {
                    "ok": True,
                    "paper_only": True,
                    "order": order,
                },
            )
        except Exception as exc:
            send(self, 400, {"ok": False, "error": str(exc)[:240]})
