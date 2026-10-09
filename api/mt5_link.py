"""AEGIS MT5 DEMO pairing: owner-enrolled, read-only ledger ingestion.

This API has no MT5 client and no broker order endpoint. The desktop bridge
checks its locally logged-in MT5 account's DEMO flag before submitting a
bounded snapshot. Client-provided provenance is not cryptographic proof of
broker execution; only trusted bridge installations should be enrolled.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import secrets
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlsplit

from aegis.forward_broker import _connect
from aegis.demo_sync import store_demo_snapshot, validate_demo_snapshot
from api.stage3 import authorize_control_request


MAX_BODY = 100_000
PAIR_TTL_SECONDS = 900
_SOURCE_PATTERN = re.compile(r"^mt5-demo-[a-f0-9]{20}$")
_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{40,60}$")


def token_digest(raw: str) -> str:
    if not isinstance(raw, str) or not _TOKEN_PATTERN.fullmatch(raw):
        raise ValueError("invalid_pairing_token")
    return hashlib.sha256(raw.encode("ascii")).hexdigest()


def validate_mt5_payload(value: object) -> dict:
    if not isinstance(value, dict):
        raise ValueError("invalid_mt5_snapshot")
    forbidden = {"password", "login", "api_key", "secret", "server_password"}
    if any(field in value for field in forbidden):
        raise ValueError("unexpected_sensitive_fields")
    validate_demo_snapshot(value)
    if value.get("provider") != "MT5_DEMO" or not _SOURCE_PATTERN.fullmatch(
        str(value.get("account_ref", ""))):
        raise ValueError("not_mt5_demo")
    symbol = value.get("market")
    if not isinstance(symbol, str) or len(symbol) > 32 or not re.fullmatch(
        r"[a-zA-Z0-9._-]+", symbol):
        raise ValueError("invalid_symbol")
    if not (symbol.upper().startswith("XAU") or symbol.upper().startswith("GOLD")):
        raise ValueError("gold_only")
    if len(value["fills"]) > 200 or len(value["open_positions"]) > 100:
        raise ValueError("snapshot_too_large")
    for metric in ("balance", "equity"):
        try:
            n = float(value[metric])
        except (KeyError, TypeError, ValueError, OverflowError):
            raise ValueError("invalid_account_metric") from None
        if not math.isfinite(n) or n < 0 or n > 1_000_000_000_000:
            raise ValueError("invalid_account_metric")
    for fill in value["fills"]:
        if not isinstance(fill, dict) or fill.get("symbol") != symbol or fill.get("side") not in ("BUY", "SELL"):
            raise ValueError("invalid_demo_fill")
        for field in ("price", "qty"):
            try:
                n = float(fill[field])
            except (KeyError, ValueError, TypeError, OverflowError):
                raise ValueError("invalid_demo_fill") from None
            if not math.isfinite(n) or n <= 0:
                raise ValueError("invalid_demo_fill")
        try:
            ts = datetime.fromisoformat(fill["executed_at"].replace("Z", "+00:00"))
        except (KeyError, ValueError, TypeError, AttributeError):
            raise ValueError("invalid_demo_fill_time") from None
        if ts.tzinfo is None or abs((datetime.now(timezone.utc) - ts.astimezone(timezone.utc)).total_seconds()) > 32 * 86400:
            raise ValueError("invalid_demo_fill_time")
    return value


def schema_ready(cur) -> bool:
    cur.execute("""SELECT to_regclass('aegis.mt5_pairings') IS NOT NULL AS pairing,
                   to_regclass('aegis.demo_account_state') IS NOT NULL AS accounts,
                   to_regclass('aegis.demo_fills') IS NOT NULL AS fills""")
    r = cur.fetchone()
    return bool(r["pairing"] and r["accounts"] and r["fills"])


def status_report(cur) -> dict:
    if not schema_ready(cur):
        return {"ok": True, "state": "SETUP_REQUIRED", "connected": False,
                "reason": "mt5_pairing_schema_missing", "live_execution_enabled": False,
                "demo_order_execution_enabled": False}
    cur.execute("""SELECT state, market, last_synced,
                          expires_at FROM aegis.mt5_pairings
                   WHERE state = 'ACTIVE'
                      OR (state = 'PENDING' AND expires_at > now())
                   ORDER BY CASE WHEN state='ACTIVE' THEN 0 ELSE 1 END,
                            last_synced DESC NULLS LAST, created_at DESC LIMIT 1""")
    item = cur.fetchone()
    state = "UNLINKED"
    last_synced = None
    market = None
    if item:
        market = item["market"] if item["state"] == "ACTIVE" else None
        last_synced = item["last_synced"]
        if item["state"] == "PENDING":
            state = "AWAITING_CONNECTOR"
        else:
            seconds = (datetime.now(timezone.utc) - last_synced).total_seconds() if last_synced else float("inf")
            state = "CONNECTED_DEMO" if 0 <= seconds < 300 else "STALE_DEMO"
    return {"ok": True, "state": state, "connected": state == "CONNECTED_DEMO",
            "market": market, "last_synced": last_synced,
            "live_execution_enabled": False, "demo_order_execution_enabled": False}


def owner_check(headers) -> tuple[int, str] | None:
    return authorize_control_request(
        expected_token=os.getenv("AEGIS_CONTROL_TOKEN", ""),
        supplied_auth=headers.get("Authorization", ""),
        origin=headers.get("Origin", ""),
        host=headers.get("Host", ""),
        fetch_site=headers.get("Sec-Fetch-Site", ""))


def owner_action(action: str, headers: object) -> tuple[int, dict]:
    auth = owner_check(headers)
    if auth:
        return auth[0], {"ok": False, "error": auth[1]}
    with _connect() as conn, conn.cursor() as cur:
        if not schema_ready(cur):
            return 503, {"ok": False, "error": "mt5_pairing_schema_missing"}
        if action == "create":
            secret = secrets.token_urlsafe(32)
            digest = token_digest(secret)
            cur.execute("""UPDATE aegis.mt5_pairings SET state='REVOKED',revoked_at=now()
                       WHERE state='PENDING'""")
            cur.execute("""INSERT INTO aegis.mt5_pairings (token_sha256,state,expires_at)
                       VALUES (%s,'PENDING',now() + interval '15 minutes')""", (digest,))
            return 201, {"ok": True, "pairing_token": secret,
                         "expires_in_seconds": PAIR_TTL_SECONDS,
                         "demo_order_execution_enabled": False}
        if action == "revoke":
            cur.execute("""UPDATE aegis.mt5_pairings SET state='REVOKED',revoked_at=now()
                       WHERE state IN ('PENDING','ACTIVE')""")
            return 200, {"ok": True, "state": "DISCONNECTED",
                         "demo_order_execution_enabled": False}
        return 400, {"ok": False, "error": "invalid_owner_action"}


def ingest_snapshot(authorization: str, snapshot: object) -> tuple[int, dict]:
    """Only the one credential scoped to a paired read-only MT5 bridge can ingest."""
    if not isinstance(authorization, str) or not authorization.startswith("Bearer "):
        return 401, {"ok": False, "error": "invalid_connector_token"}
    try:
        digest = token_digest(authorization[len("Bearer "):])
        doc = validate_mt5_payload(snapshot)
    except ValueError as exc:
        return 422, {"ok": False, "error": str(exc)}
    with _connect() as conn, conn.cursor() as cur:
        if not schema_ready(cur):
            return 503, {"ok": False, "error": "mt5_pairing_schema_missing"}
        cur.execute("""SELECT pairing_id,state,expires_at,source_id FROM aegis.mt5_pairings
                       WHERE token_sha256=%s FOR UPDATE""", (digest,))
        row = cur.fetchone()
        if not row or row["state"] == "REVOKED":
            return 401, {"ok": False, "error": "connector_not_authorized"}
        if row["state"] == "PENDING" and row["expires_at"] <= datetime.now(timezone.utc):
            return 410, {"ok": False, "error": "pairing_code_expired"}
        if row["state"] == "ACTIVE" and not hmac.compare_digest(
            row["source_id"] or "", doc["account_ref"]):
            return 403, {"ok": False, "error": "different_mt5_demo_account"}
        # Reconciliation happens atomically with the session activation.
        stats = store_demo_snapshot(conn, doc)
        cur.execute("""UPDATE aegis.mt5_pairings SET state='ACTIVE',
                       source_id=%s,market=%s,last_synced=now()
                       WHERE pairing_id=%s AND state IN ('PENDING','ACTIVE')""",
                    (doc["account_ref"], doc["market"], row["pairing_id"]))
    return 200, {"ok": True, "state": "CONNECTED_DEMO",
                 "new_fills": stats["new_fills"],
                 "demo_order_execution_enabled": False,
                 "live_execution_enabled": False}


class handler(BaseHTTPRequestHandler):
    def _reply(self, status: int, payload: dict):
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store, private")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if urlsplit(self.path).query:
            self._reply(400, {"ok": False, "error": "unexpected_parameters"})
            return
        try:
            with _connect() as conn, conn.cursor() as cur:
                self._reply(200, status_report(cur))
        except Exception:
            self._reply(503, {"ok": False, "error": "mt5_pairing_status_unavailable"})

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if n < 2 or n > MAX_BODY or self.headers.get("Transfer-Encoding"):
                self._reply(413, {"ok": False, "error": "invalid_payload_size"})
                return
            data = json.loads(self.rfile.read(n).decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("payload_must_be_an_object")
            action = data.get("action")
            if action in ("create", "revoke"):
                status, result = owner_action(action, self.headers)
            elif action == "sync":
                status, result = ingest_snapshot(self.headers.get("Authorization", ""),
                                                 data.get("snapshot"))
            else:
                status, result = 400, {"ok": False, "error": "unknown_action"}
            self._reply(status, result)
        except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
            self._reply(400, {"ok": False, "error": "invalid_request"})
        except Exception:
            self._reply(503, {"ok": False, "error": "mt5_pairing_service_unavailable"})
