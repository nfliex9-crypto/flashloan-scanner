"""Gold spot and Bitcoin research market board.

BTC from public Kraken XBTUSD hourly candles; GOLD spot from licensed
Twelve Data XAU/USD time series only if TWELVEDATA_API_KEY is configured.
No GLD ETF, gold futures, or made-up fallback masquerading as spot.
All quotes carry source age; no use for order execution.
"""
from __future__ import annotations
import json,os,urllib.request,urllib.parse,math
from datetime import datetime,timezone
from .live_lab import fetch_ohlc

def _fetch_json(url):
    req=urllib.request.Request(url,headers={"User-Agent":"AEGIS-Forward-Research/1.0"})
    with urllib.request.urlopen(req,timeout=10) as r:return json.loads(r.read().decode("utf-8"))

def _quote(symbol,price,stamp,source,kind,previous=None):
    age=(datetime.now(timezone.utc)-stamp).total_seconds()
    change=(price/previous-1.0) if previous and previous>0 else None
    return {"symbol":symbol,"price":price,"observed_at":stamp.isoformat(),"age_seconds":round(age),
            "fresh":0<=age<=3900,"source":source,"type":kind,"change":change,
            "execution_enabled":False}

def priority_market_board():
    results={"ok":True,"paper_only":True,"live_money":False,"generated_at":datetime.now(timezone.utc).isoformat(),"markets":[]}
    try:
        candles=fetch_ohlc("XBTUSD")
        # The Kraken final row is the current OPEN hour; never use it for a closed-bar strategy.
        row=candles[-1]
        prev=candles[-25] if len(candles)>=25 else candles[-2]
        results["markets"].append(_quote("BTC/USD",row.close,
            datetime.fromtimestamp(row.ts,tz=timezone.utc),"Kraken XBTUSD 1h (open bar snapshot)","SPOT_CRYPTO",prev.close))
    except Exception as e:
        results["markets"].append({"symbol":"BTC/USD","connected":False,"error":str(e)[:130],"execution_enabled":False})
    from .oanda_gold import fetch_practice_gold_price
    oanda=fetch_practice_gold_price()
    if oanda.get("connected"):
        results["markets"].append(oanda)
        return results
    key=os.getenv("TWELVEDATA_API_KEY")
    if not key:
        results["markets"].append(oanda if oanda.get("status")!="WAITING_FOR_OANDA_PRACTICE_CREDENTIALS" else {
            **oanda,"preferred_source":"OANDA","note":"Use existing OANDA Practice account; Twelve Data is optional fallback"})
    else:
        try:
            query=urllib.parse.urlencode({"symbol":"XAU/USD","interval":"1h","outputsize":"3","timezone":"UTC","apikey":key})
            payload=_fetch_json("https://api.twelvedata.com/time_series?"+query)
            rows=payload.get("values",[])
            if payload.get("status")=="error" or len(rows)<2:
                raise ValueError(str(payload.get("message","Missing spot gold hourly candles"))[:140])
            latest,prev=rows[0],rows[1]
            price=float(latest["close"])
            if not math.isfinite(price) or price<=0:raise ValueError("Invalid spot gold quote")
            # Twelve Data datetime on time series uses selected timezone, force UTC explicitly below.
            stamp=datetime.fromisoformat(latest["datetime"].replace("Z","+00:00"))
            if stamp.tzinfo is None:stamp=stamp.replace(tzinfo=timezone.utc)
            q=_quote("XAU/USD",price,stamp.astimezone(timezone.utc),"Twelve Data XAU/USD 1h","SPOT_GOLD",float(prev["close"]))
            # A bar timestamp is the start of an interval, NOT an exact live tick.
            q["note"]="Timestamp is 1-hour bar start; not an executable spot-gold quote"
            results["markets"].append(q)
        except Exception as e:
            results["markets"].append({"symbol":"XAU/USD","connected":False,"source":"Twelve Data","type":"SPOT_GOLD",
                "error":str(e)[:150],"execution_enabled":False})
    return results
