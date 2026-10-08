"""Read-only OANDA v20 gold price adapter.

Practice environment ONLY. This module never sends POST/PATCH/PUT/DELETE
and cannot submit an order. XAU_USD availability depends on account region.
"""
from __future__ import annotations
import json,math,os,urllib.error,urllib.parse,urllib.request
from datetime import datetime,timezone

PRACTICE_URL="https://api-fxpractice.oanda.com"


def parse_gold_price(payload:dict,now:datetime|None=None)->dict:
    now=now or datetime.now(timezone.utc)
    entries=[p for p in payload.get("prices",[]) if p.get("instrument")=="XAU_USD"]
    if not entries:raise ValueError("XAU_USD not returned; instrument may be unavailable for this account")
    p=entries[0]
    bids=p.get("bids") or []
    asks=p.get("asks") or []
    if not bids or not asks:raise ValueError("OANDA price missing bid/ask")
    bid=float(bids[0]["price"]);ask=float(asks[0]["price"])
    if not all(math.isfinite(x) and x>0 for x in (bid,ask)) or ask<bid:
        raise ValueError("Invalid OANDA bid/ask")
    ts=datetime.fromisoformat(str(p["time"]).replace("Z","+00:00")).astimezone(timezone.utc)
    age=(now-ts).total_seconds()
    status=str(p.get("status","unknown")).lower()
    return {"symbol":"XAU/USD","price":round((bid+ask)/2,5),
            "bid":bid,"ask":ask,"spread":round(ask-bid,5),
            "observed_at":ts.isoformat(),"age_seconds":round(age),
            "fresh":0<=age<=120 and status=="tradeable",
            "tradeable":status=="tradeable",
            "status":"RECENT_PRACTICE_QUOTE" if 0<=age<=120 and status=="tradeable" else "STALE_OR_MARKET_CLOSED",
            "source":"OANDA fxTrade Practice XAU_USD bid/ask",
            "type":"SPOT_GOLD_BROKER_QUOTE","execution_enabled":False}


def fetch_practice_gold_price()->dict:
    token=os.getenv("OANDA_API_TOKEN","").strip()
    account=os.getenv("OANDA_ACCOUNT_ID","").strip()
    if not token or not account:
        return {"symbol":"XAU/USD","connected":False,"source":"OANDA fxTrade Practice",
                "type":"SPOT_GOLD_BROKER_QUOTE","required_env":["OANDA_API_TOKEN","OANDA_ACCOUNT_ID"],
                "status":"WAITING_FOR_OANDA_PRACTICE_CREDENTIALS","execution_enabled":False}
    if not all(ch.isascii() and (ch.isalnum() or ch=="-") for ch in account):
        return {"symbol":"XAU/USD","connected":False,"source":"OANDA fxTrade Practice",
                "status":"INVALID_ACCOUNT_ID","execution_enabled":False}
    url=f"{PRACTICE_URL}/v3/accounts/{account}/pricing?"+urllib.parse.urlencode({"instruments":"XAU_USD"})
    req=urllib.request.Request(url,headers={"Authorization":"Bearer "+token,"Accept":"application/json",
        "User-Agent":"AEGIS-Paper-Research/1.0"},method="GET")
    try:
        with urllib.request.urlopen(req,timeout=9) as res:
            result=json.loads(res.read().decode("utf-8"))
        quote=parse_gold_price(result)
        quote["connected"]=True
        return quote
    except urllib.error.HTTPError as e:
        return {"symbol":"XAU/USD","connected":False,"source":"OANDA fxTrade Practice",
                "status":"OANDA_HTTP_ERROR","http_status":e.code,
                "error":"Account authorization or XAU_USD availability could not be verified",
                "execution_enabled":False}
    except (ValueError,KeyError,urllib.error.URLError,TimeoutError) as e:
        return {"symbol":"XAU/USD","connected":False,"source":"OANDA fxTrade Practice",
                "status":"OANDA_DATA_UNAVAILABLE",
                "error":str(e)[:160] if isinstance(e,ValueError) else "Price feed unavailable",
                "execution_enabled":False}
