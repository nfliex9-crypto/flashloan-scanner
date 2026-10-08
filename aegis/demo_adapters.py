"""Read-only broker DEMO ledger adapters. No order creation endpoints.

MT5 requires an already logged-in Windows terminal. Binance SPOT Demo
is strictly pinned to its isolated demo-api domain, never production.
Tokens are never printed or stored. Accessors do not send trade orders.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

BINANCE_SPOT_DEMO_API = "https://demo-api.binance.com"
BTC_SYMBOL = "BTCUSDT"


class DemoConnectionError(RuntimeError):
    pass


def _account_ref(provider: str, identity: str) -> str:
    return provider.lower() + "-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]


def read_mt5_demo_gold(*, mt5=None, symbol: str = "XAUUSD", days: int = 14,
                       now: datetime | None = None) -> dict:
    """Audit broker-confirmed DEMO XAU deals and open positions; never order_send.

    Symbol suffixes vary by broker: XAUUSD, XAUUSDm, GOLD etc.
    A demo check is mandatory even though this method is read-only.
    """
    if mt5 is None:
        try:
            import MetaTrader5 as mt5
        except ImportError as exc:
            raise DemoConnectionError("MT5 requires Windows terminal and MetaTrader5 Python package") from exc
    if not symbol or len(symbol) > 32 or not symbol.replace(".", "").replace("_", "").isalnum():
        raise ValueError("Invalid broker gold symbol")
    if not 1 <= days <= 30:
        raise ValueError("MT5 history window must be 1-30 days")
    if not mt5.initialize():
        raise DemoConnectionError("MT5 terminal not connected")
    try:
        info = mt5.account_info()
        if info is None:
            raise DemoConnectionError("MT5 account information unavailable")
        if int(info.trade_mode) != int(mt5.ACCOUNT_TRADE_MODE_DEMO):
            raise DemoConnectionError("Refusing non-DEMO MT5 account")
        if mt5.symbol_info(symbol) is None:
            raise DemoConnectionError("Gold symbol not available at connected demo broker")
        now = now or datetime.now(timezone.utc)
        deals = mt5.history_deals_get(now-timedelta(days=days),now,group="*"+symbol+"*")
        positions = mt5.positions_get(symbol=symbol)
        if deals is None or positions is None:
            raise DemoConnectionError("MT5 demo history or positions query failed")
        account_id = _account_ref("mt5-demo",str(info.login)+":"+str(info.server))
        fills = []
        for item in deals:
            d=item._asdict() if hasattr(item,"_asdict") else vars(item)
            if d.get("symbol") != symbol:
                continue
            if int(d.get("type",-1)) not in (int(mt5.DEAL_TYPE_BUY),int(mt5.DEAL_TYPE_SELL)):
                continue
            tm=int(d.get("time_msc") or (d.get("time",0)*1000))
            fills.append({
                "external_id":str(d["ticket"]),"order_id":str(d.get("order","")),
                "position_id":str(d.get("position_id","")),"symbol":symbol,
                "side":"BUY" if int(d["type"])==int(mt5.DEAL_TYPE_BUY) else "SELL",
                "entry_kind":str(d.get("entry","")),"price":float(d["price"]),
                "qty":float(d["volume"]),"fee":float(d.get("commission",0)),
                "fee_asset":str(info.currency),
                "net_pnl":sum(float(d.get(k,0)) for k in ("profit","commission","swap")),
                "executed_at":datetime.fromtimestamp(tm/1000,timezone.utc).isoformat(),
                "agent_id":str(d.get("magic") or "") or None,
            })
        active = []
        for pos in positions:
            d=pos._asdict() if hasattr(pos,"_asdict") else vars(pos)
            active.append({
                "external_id":str(d["ticket"]),"symbol":symbol,
                "side":"BUY" if int(d["type"])==0 else "SELL",
                "qty":float(d["volume"]),"entry_price":float(d["price_open"]),
                "mark_price":float(d["price_current"]),
                "unrealized_pnl":float(d["profit"]),
                "stop_price":float(d.get("sl",0)),
                "target_price":float(d.get("tp",0)),
            })
        return {
            "provider":"MT5_DEMO","account_ref":account_id,
            "market":symbol,"account_type":"DEMO",
            "currency":str(info.currency),"equity":float(info.equity),
            "balance":float(info.balance),
            "fills":fills,"open_positions":active,
            "open_orders":[],
            "source_of_truth":"MT5 broker execution history",
            "live_execution_enabled":False,
        }
    finally:
        mt5.shutdown()


class BinanceSpotDemoReader:
    """Never accepts a configurable base URL; no method can POST orders."""

    def __init__(self, api_key: str, api_secret: str):
        if not api_key or not api_secret:
            raise DemoConnectionError("Binance DEMO API keys not configured")
        self._key = api_key
        self._secret = api_secret.encode("utf-8")

    def _signed_get(self, path: str, **params):
        if path not in ("/api/v3/account","/api/v3/openOrders",
                        "/api/v3/myTrades","/api/v3/allOrders"):
            raise ValueError("Endpoint not allowlisted for read-only demo ledger")
        payload = {"timestamp":str(int(time.time()*1000)),"recvWindow":"5000"}
        payload.update({k:str(v) for k,v in params.items()})
        encoded=urllib.parse.urlencode(payload)
        digest=hmac.new(self._secret,encoded.encode("utf-8"),hashlib.sha256).hexdigest()
        url=BINANCE_SPOT_DEMO_API+path+"?"+encoded+"&signature="+digest
        req=urllib.request.Request(
            url,headers={"X-MBX-APIKEY":self._key,"User-Agent":"AEGIS-READONLY-DEMO/1.0"},
            method="GET")
        try:
            with urllib.request.urlopen(req,timeout=10) as response:
                body=json.loads(response.read().decode("utf-8"))
        except (urllib.error.HTTPError,urllib.error.URLError,TimeoutError,ValueError) as exc:
            # Never leak URLs, tokens, signature or request details in errors.
            raise DemoConnectionError("Binance demo ledger currently unavailable") from None
        if isinstance(body,dict) and "code" in body and int(body["code"])<0:
            raise DemoConnectionError("Binance demo rejected this read request")
        return body

    def snapshot(self, symbol: str = BTC_SYMBOL) -> dict:
        if symbol != BTC_SYMBOL:
            raise ValueError("Only BTCUSDT demo spot is authorized")
        info=self._signed_get("/api/v3/account")
        if not isinstance(info,dict) or info.get("accountType") != "SPOT":
            raise DemoConnectionError("Unexpected Binance demo account response")
        fills_raw=self._signed_get("/api/v3/myTrades",symbol=symbol,limit=500)
        orders=self._signed_get("/api/v3/openOrders",symbol=symbol)
        if not isinstance(fills_raw,list) or not isinstance(orders,list):
            raise DemoConnectionError("Unexpected Binance demo execution history response")
        fills=[{
            "external_id":str(t["id"]),"order_id":str(t["orderId"]),
            "position_id":None,"symbol":symbol,
            "side":"BUY" if t["isBuyer"] else "SELL",
            "entry_kind":"EXECUTION","price":float(t["price"]),
            "qty":float(t["qty"]),"fee":float(t["commission"]),
            "fee_asset":str(t["commissionAsset"]),"net_pnl":None,
            "executed_at":datetime.fromtimestamp(int(t["time"])/1000,timezone.utc).isoformat(),
            "agent_id":None,
        } for t in fills_raw]
        balances={
            b["asset"]:{"free":float(b["free"]),"locked":float(b["locked"])}
            for b in info.get("balances",[])
            if b.get("asset") in ("BTC","USDT")
        }
        active=[{
            "external_id":str(o["orderId"]),"symbol":symbol,
            "side":str(o["side"]),"type":str(o["type"]),
            "qty":float(o["origQty"]),"filled":float(o["executedQty"]),
            "price":float(o["price"]),"status":str(o["status"])
        } for o in orders]
        account_id=_account_ref("binance-demo",str(info.get("accountType"))+":BTCUSDT")
        return {
            "provider":"BINANCE_SPOT_DEMO","account_ref":account_id,
            "market":symbol,"account_type":"DEMO",
            "currency":"USDT","balance":None,"equity":None,
            "spot_balances":balances,"fills":fills,
            "open_positions":[],"open_orders":active,
            "source_of_truth":"Binance Spot Demo account trades",
            "live_execution_enabled":False,
        }


def read_binance_spot_demo() -> dict:
    return BinanceSpotDemoReader(
        os.getenv("BINANCE_DEMO_API_KEY",""),
        os.getenv("BINANCE_DEMO_API_SECRET","")
    ).snapshot()
