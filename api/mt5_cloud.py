"""Cloud-only MT5 DEMO reader via MetaApi. No Windows, broker password or orders.

Account must be provisioned by user on app.metaapi.cloud using an INVESTOR
(read-only) MT5 Demo password. Configure token and account id in the protected
Vercel preview environment, never in the public repository or website form.
Only allowlisted MetaApi HTTPS read endpoints are callable by this code.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler

from aegis.demo_sync import store_demo_snapshot, validate_demo_snapshot
from aegis.forward_broker import _connect
from api.stage3 import authorize_control_request

REGIONS = frozenset(("new-york", "london"))
ID_PATTERN = re.compile(r"^[a-zA-Z0-9-]{20,64}$")
SYMBOL_PATTERN = re.compile(r"^(?:XAU[A-Za-z0-9._-]{0,24}|GOLD[A-Za-z0-9._-]{0,24})$", re.I)
MAX_RESPONSE = 750_000


class CloudUnavailable(Exception):
    pass


def configuration() -> dict | None:
    token = os.getenv("AEGIS_METAAPI_TOKEN", "")
    account = os.getenv("AEGIS_METAAPI_ACCOUNT_ID", "")
    region = os.getenv("AEGIS_METAAPI_REGION", "new-york")
    symbol = os.getenv("AEGIS_MT5_GOLD_SYMBOL", "XAUUSD")
    if not token or not account:
        return None
    # Fail closed on invalid admin-provided values. A fixed host allowlist
    # prevents SSRF; no user-configurable URL or HTTP method exists here.
    if region not in REGIONS or not ID_PATTERN.fullmatch(account):
        raise CloudUnavailable("invalid_cloud_configuration")
    if not SYMBOL_PATTERN.fullmatch(symbol):
        raise CloudUnavailable("invalid_gold_symbol")
    return {"token": token, "account": account, "region": region, "symbol": symbol}


def metaapi_get(config: dict, suffix: str):
    if suffix not in ("/account-information", "/positions", "/symbols") and not suffix.startswith("/history-deals/time/"):
        raise ValueError("MetaApi endpoint forbidden")
    if suffix.startswith("/history-deals/time/") and not re.fullmatch(
            r"/history-deals/time/[0-9TZ:.-]+/[0-9TZ:.-]+\\?limit=[0-9]{1,3}",suffix):
        raise ValueError("MetaApi history range forbidden")
    base = "https://mt-client-api-v1." + config["region"] + ".agiliumtrade.ai"
    url = base + "/users/current/accounts/" + config["account"] + suffix
    req = urllib.request.Request(
        url, headers={"auth-token": config["token"], "Accept": "application/json",
                      "User-Agent": "AEGIS-MT5-DEMO-READ-ONLY/1.0"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise CloudUnavailable("oversized_metaapi_response")
            return json.loads(raw)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError, UnicodeError) as exc:
        # Never forward upstream URLs, login names or token-bearing exceptions.
        raise CloudUnavailable("metaapi_read_unavailable") from None


def verified_demo_info(config: dict) -> dict:
    info = metaapi_get(config, "/account-information")
    if not isinstance(info, dict) or info.get("type") != "ACCOUNT_TRADE_MODE_DEMO":
        raise CloudUnavailable("not_verified_demo_account")
    for key in ("balance", "equity"):
        try:
            amount = float(info[key])
        except (ValueError, TypeError, KeyError, OverflowError):
            raise CloudUnavailable("invalid_broker_account_info") from None
        if not math.isfinite(amount) or amount < 0 or amount > 1_000_000_000_000:
            raise CloudUnavailable("invalid_broker_account_info")
    if not str(info.get("login", "")).isdigit() or not isinstance(info.get("server"), str):
        raise CloudUnavailable("invalid_broker_account_info")
    return info


def snapshot_from_metaapi(config: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    info = verified_demo_info(config)
    symbols = metaapi_get(config, "/symbols")
    symbol = config["symbol"]
    if not isinstance(symbols, list) or symbol not in symbols:
        raise CloudUnavailable("gold_symbol_not_available")
    positions = metaapi_get(config, "/positions")
    start = (now - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    end = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    deals = metaapi_get(config, "/history-deals/time/"+start+"/"+end+"?limit=200")
    if not isinstance(positions, list) or not isinstance(deals, list):
        raise CloudUnavailable("invalid_metaapi_ledger")
    if len(positions) > 100 or len(deals) > 200:
        raise CloudUnavailable("snapshot_too_large")
    source = str(info["login"])+":"+str(info["server"])
    fingerprint = "mt5-demo-"+hashlib.sha256(source.encode()).hexdigest()[:20]
    fills=[]
    for deal in deals:
        if deal.get("symbol") != symbol or deal.get("type") not in ("DEAL_TYPE_BUY", "DEAL_TYPE_SELL"):
            continue
        # Models are sourced directly from MT5; no invented execution IDs.
        fills.append({
            "external_id": str(deal["id"]), "order_id": str(deal.get("orderId","")),
            "position_id": str(deal.get("positionId","")), "symbol": symbol,
            "side": "BUY" if deal["type"] == "DEAL_TYPE_BUY" else "SELL",
            "entry_kind": str(deal.get("entryType","")), "price": float(deal["price"]),
            "qty": float(deal["volume"]), "fee": float(deal.get("commission",0)),
            "fee_asset": str(info.get("currency","USD")),
            "net_pnl": sum(float(deal.get(k,0)) for k in ("profit","commission","swap")),
            "executed_at": str(deal["time"]),
            "agent_id": str(deal.get("magic") or "") or None})
    active=[]
    for p in positions:
        if p.get("symbol") != symbol:continue
        active.append({
            "external_id": str(p["id"]), "symbol": symbol,
            "side": "BUY" if p.get("type") == "POSITION_TYPE_BUY" else "SELL",
            "qty": float(p["volume"]), "entry_price": float(p["openPrice"]),
            "mark_price": float(p.get("currentPrice",0)),
            "unrealized_pnl": float(p.get("profit",0)),
            "stop_price": float(p.get("stopLoss",0) or 0),
            "target_price": float(p.get("takeProfit",0) or 0)})
    doc={"provider":"MT5_DEMO","account_ref":fingerprint,"market":symbol,
         "account_type":"DEMO","currency":str(info.get("currency","USD")),
         "balance":float(info["balance"]),"equity":float(info["equity"]),
         "fills":fills,"open_positions":active,"open_orders":[],
         "source_of_truth":"MetaApi MT5 Demo broker history (cloud read-only)",
         "live_execution_enabled":False}
    validate_demo_snapshot(doc)
    return doc


def public_status() -> dict:
    cfg = configuration()
    if cfg is None:
        return {"ok":True,"state":"SETUP_REQUIRED","connected":False,
                "setup":"metaapi_environment_variables_missing",
                "live_execution_enabled":False,"demo_order_execution_enabled":False}
    try:
        verified_demo_info(cfg)
    except CloudUnavailable as exc:
        reason = str(exc)
        return {"ok":True,"state":"NOT_VERIFIED","connected":False,
                "reason": reason if reason in ("not_verified_demo_account",
                              "invalid_broker_account_info") else "cloud_api_unavailable",
                "live_execution_enabled":False,"demo_order_execution_enabled":False}
    return {"ok":True,"state":"CONNECTED_DEMO","connected":True,
            "mode":"METAAPI_CLOUD_READ_ONLY","source":"METAAPI_MT5_DEMO",
            "live_execution_enabled":False,"demo_order_execution_enabled":False}


def sync_readonly(headers) -> tuple[int, dict]:
    auth = authorize_control_request(
        expected_token=os.getenv("AEGIS_CONTROL_TOKEN",""),
        supplied_auth=headers.get("Authorization",""),
        origin=headers.get("Origin",""),
        host=headers.get("Host",""),
        fetch_site=headers.get("Sec-Fetch-Site",""))
    if auth:return auth[0],{"ok":False,"error":auth[1]}
    cfg = configuration()
    if cfg is None:return 503,{"ok":False,"error":"metaapi_not_configured"}
    try:
        snap = snapshot_from_metaapi(cfg)
        with _connect() as conn:
            result = store_demo_snapshot(conn, snap)
        return 200, {"ok":True,"state":"CONNECTED_DEMO",
                     "new_fills":result["new_fills"],
                     "open_positions":result["open_positions"],
                     "demo_order_execution_enabled":False}
    except CloudUnavailable as exc:
        return 503, {"ok":False,"error":str(exc)}
    except Exception:
        # Do not disclose PostgreSQL/MetaApi credentials in errors.
        return 503,{"ok":False,"error":"demo_ledger_sync_unavailable"}


class handler(BaseHTTPRequestHandler):
    def _reply(self, code: int, value: dict):
        body=json.dumps(value).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Cache-Control","no-store, private")
        self.send_header("X-Content-Type-Options","nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?",1)[-1] != self.path:
            self._reply(400,{"ok":False,"error":"query_not_supported"})
            return
        try:
            self._reply(200,public_status())
        except CloudUnavailable:
            self._reply(200,{"ok":True,"state":"CONFIG_INVALID","connected":False,
                             "demo_order_execution_enabled":False})
        except Exception:
            self._reply(503,{"ok":False,"error":"metaapi_status_unavailable"})

    def do_POST(self):
        try:
            size=int(self.headers.get("Content-Length","0"))
            if size < 2 or size > 128 or self.headers.get("Transfer-Encoding"):
                self._reply(413,{"ok":False,"error":"invalid_payload_size"})
                return
            body=json.loads(self.rfile.read(size))
            if body != {"action":"sync"}:
                self._reply(400,{"ok":False,"error":"invalid_action"})
                return
            status,result=sync_readonly(self.headers)
            self._reply(status,result)
        except (ValueError,TypeError,json.JSONDecodeError):
            self._reply(400,{"ok":False,"error":"invalid_payload"})
        except Exception:
            self._reply(503,{"ok":False,"error":"metaapi_sync_unavailable"})
