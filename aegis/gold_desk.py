"""AEGIS Gold Desk: real third-party indicative spot, no simulated prices.

This endpoint is deliberately separate from Pepperstone/cTrader executions.
Gold-API publishes XAU/USD per troy ounce, not an executable Pepperstone
bid/ask. A verified provider timestamp is required; stale weekend data
must not be reported as a live tradeable price.
"""
from __future__ import annotations

from datetime import datetime,timezone,timedelta
from math import isfinite
import json
import urllib.request
import urllib.error

SOURCE_URL="https://api.gold-api.com/price/XAU"
MAX_RESPONSE_BYTES=12000
MAX_AGE_SECONDS=300


def parse_gold_spot(doc:dict, *, now:datetime|None=None)->dict:
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Missing timezone on spot quote evaluation")
    if not isinstance(doc,dict) or doc.get("symbol")!="XAU":
        raise ValueError("Provider symbol is not gold")
    if doc.get("currency")!="USD":
        raise ValueError("Gold quote must be denominated in USD")
    price=doc.get("price")
    if type(price) not in (int,float) or not isfinite(price) or not 100<=price<=50000:
        raise ValueError("Invalid indicative gold price")
    stamp=doc.get("updatedAt")
    if not isinstance(stamp,str) or len(stamp)>45:
        raise ValueError("Gold provider timestamp absent")
    try:
        published=datetime.fromisoformat(stamp.replace("Z","+00:00"))
    except ValueError:
        raise ValueError("Gold provider timestamp invalid") from None
    if published.tzinfo is None:
        raise ValueError("Gold provider timestamp timezone absent")
    published=published.astimezone(timezone.utc)
    seconds=(now-published).total_seconds()
    if not isfinite(seconds) or seconds < -120:
        raise ValueError("Gold provider timestamp lies in the future")
    is_fresh=0<=seconds<=MAX_AGE_SECONDS
    # Independent spot providers can refresh timestamps on weekends even when
    # broker CFDs are closed. Do not label a refreshed weekend reference as
    # a current tradable price. Sunday reopening differs across brokers/DST.
    weekend=now.weekday() in (5,6)
    state=("MARKET_CLOSED_WEEKEND" if weekend else
           "CURRENT" if is_fresh else "STALE_SOURCE_QUOTE")
    return {
        "source":"gold-api.com",
        "source_url":"https://gold-api.com/",
        "instrument":"XAU/USD",
        "asset_symbol":"XAU",
        "currency":"USD",
        "unit":"USD_PER_TROY_OUNCE",
        "kind":"INDICATIVE_SPOT_REFERENCE_NOT_BROKER_EXECUTABLE",
        "provider_updated_at":published.isoformat(),
        "age_seconds":max(0,round(seconds)),
        "fresh":is_fresh and not weekend,
        "provider_timestamp_fresh":is_fresh,
        "market_session":"WEEKEND_CLOSED" if weekend else "NOT_VERIFIED_FROM_BROKER",
        "state":state,
        "price":round(float(price),4) if is_fresh and not weekend else None,
        "last_known_price":round(float(price),4),
        "spread":None,
        "pepperstone_bid":None,
        "pepperstone_ask":None,
        "trading_permission":False,
    }


def get_gold_quote(*, now:datetime|None=None) -> dict:
    req=urllib.request.Request(
        SOURCE_URL, method="GET",
        headers={"Accept":"application/json","User-Agent":"AEGIS-GOLD-INFORMATIVE-PRICE/1.0"})
    try:
        with urllib.request.urlopen(req,timeout=6) as response:
            raw=response.read(MAX_RESPONSE_BYTES+1)
        if len(raw)>MAX_RESPONSE_BYTES:
            raise ValueError("Gold response too large")
        doc=json.loads(raw)
        return parse_gold_spot(doc,now=now)
    except (urllib.error.URLError,urllib.error.HTTPError,TimeoutError,
            OSError,ValueError,UnicodeDecodeError):
        return {"source":"gold-api.com","instrument":"XAU/USD",
                "unit":"USD_PER_TROY_OUNCE",
                "kind":"INDICATIVE_SPOT_REFERENCE_NOT_BROKER_EXECUTABLE",
                "state":"SOURCE_UNAVAILABLE","fresh":False,
                "price":None,"provider_updated_at":None,
                "spread":None,"trading_permission":False}


def get_gold_desk() -> dict:
    # No broker credentials available. Avoid presenting third-party spot
    # prices as Pepperstone Demo bid/ask or real broker executions.
    quote=get_gold_quote()
    return {
        "ok":True,
        "mode":"SOURCE_BACKED_GOLD_MARKET_INFORMATION",
        "market":quote,
        "broker":{
            "provider":"PEPPERSTONE_DEMO_CTRADER",
            "state":"NOT_LINKED",
            "verified":False,
            "positions":None,
            "orders":None,
            "fills":None,
            "account_balance":None,
            "scope":"ACCOUNTS_READ_ONLY_NOT_AUTHORIZED",
            "note":"TradingView/cTrader positions require separate user-approved account link.",
        },
        "chart_url":"https://www.tradingview.com/chart/",
        "live_order_execution_enabled":False,
        "demo_order_execution_enabled":False,
    }
