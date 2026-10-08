"""Read-only IEX stock snapshots from Alpaca's documented free Basic feed.

No broker order endpoints or trading credentials are ever used for execution.
Missing credentials => explicit NOT_CONNECTED. Stale data => no live claim.
"""
from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

SYMBOLS = ("SPY","QQQ","NVDA","TSLA")
BASE_URL = "https://data.alpaca.markets/v2/stocks/snapshots"


def _iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z","+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except ValueError:
        return None


def _price(value: object) -> float | None:
    try:
        n=float(value)
        return n if math.isfinite(n) and n>0 else None
    except (TypeError,ValueError):
        return None


def parse_snapshot(symbol: str, snapshot: dict, now: datetime) -> dict:
    trade=snapshot.get("latestTrade") or {}
    minute=snapshot.get("minuteBar") or {}
    daily=snapshot.get("dailyBar") or {}
    prev=snapshot.get("prevDailyBar") or {}
    seen=_iso(trade.get("t")) or _iso(minute.get("t"))
    age=(now-seen).total_seconds() if seen else None
    price=_price(trade.get("p")) or _price(minute.get("c"))
    previous=_price(prev.get("c"))
    change=(price/previous-1) if price and previous else None
    # A recent IEX print is merely recent IEX data; never imply full SIP coverage.
    recent=bool(age is not None and 0<=age<=900 and price)
    return {
        "symbol":symbol,"price":price,"change_from_prev_close":change,
        "previous_close":previous,"last_trade_at":seen.isoformat() if seen else None,
        "age_seconds":int(age) if age is not None else None,
        "fresh":recent,"status":"RECENT_IEX" if recent else "STALE_OR_MARKET_CLOSED",
        "feed":"IEX_BASIC","source":"Alpaca Market Data",
        "market_coverage":"IEX only, not consolidated SIP",
        "paper_execution_enabled":False,
        "live_execution_enabled":False,
    }


def get_equity_quotes(now: datetime | None = None) -> dict:
    now=now or datetime.now(timezone.utc)
    key=os.getenv("ALPACA_API_KEY_ID")
    secret=os.getenv("ALPACA_API_SECRET_KEY")
    if not key or not secret:
        return {
            "ok":True,"connected":False,"mode":"NOT_CONNECTED",
            "stocks":[],"watchlist":list(SYMBOLS),
            "integration":"ALPACA_PAPER_DATA_ONLY",
            "required_environment_variables":["ALPACA_API_KEY_ID","ALPACA_API_SECRET_KEY"],
            "live_execution_enabled":False,
            "paper_execution_enabled":False,
            "message":"Connect Alpaca Paper Only market-data credentials in Vercel to retrieve IEX stock quotes.",
        }

    url=BASE_URL+"?"+urllib.parse.urlencode({"symbols":",".join(SYMBOLS),"feed":"iex"})
    req=urllib.request.Request(url,headers={
        "Accept":"application/json",
        "User-Agent":"AEGIS-Agent-City/4.0 paper-only-market-data",
        "APCA-API-KEY-ID":key,
        "APCA-API-SECRET-KEY":secret,
    })
    try:
        with urllib.request.urlopen(req,timeout=10) as resp:
            raw=json.loads(resp.read().decode("utf8"))
    except urllib.error.HTTPError as exc:
        return {"ok":False,"connected":False,"mode":"UPSTREAM_ERROR",
                "error":f"Alpaca market data HTTP {exc.code}","live_execution_enabled":False}
    snaps=raw.get("snapshots") if "snapshots" in raw else raw
    if not isinstance(snaps,dict):
        raise RuntimeError("Unexpected Alpaca snapshots response")
    stocks=[parse_snapshot(symbol,snaps.get(symbol) or {},now) for symbol in SYMBOLS]
    return {
        "ok":True,"connected":True,"mode":"REAL_IEX_SNAPSHOT",
        "generated_at":now.isoformat(),"stocks":stocks,
        "watchlist":list(SYMBOLS),"source":"Alpaca IEX Basic",
        "market_coverage":"IEX only; not full consolidated US equities market",
        "paper_execution_enabled":False,"live_execution_enabled":False,
        "note":"Stock data context only. Do not use for execution until bar/calendar/fill engine is implemented.",
    }
