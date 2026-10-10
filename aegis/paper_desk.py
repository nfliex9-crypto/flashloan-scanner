"""Fast, independently readable Kraken Paper desk.

One read-only SQL snapshot, no legacy portfolio initialization, no shadow
model, no broker API calls. All figures are from Neon stream_* receipts.
Market price is the last persisted CLOSED 1-minute candle, not a tick quote.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone, timedelta

from .forward_broker import _connect, _json_safe
from .bot_fleet import project_paper_bots

INTERVALS=(1,5,15,60,240,1440,10080)
REQUIRED=("stream_status","stream_accounts","stream_positions",
          "stream_trades","stream_decisions","stream_candles")
MAX_AGE_S=180
EXIT_FEE_RATE=0.0003  # Kraken research ledger: 3 bps estimated exit fee.


def _number(value) -> float | None:
    try:
        v=float(value)
        return v if math.isfinite(v) else None
    except (ValueError,TypeError,OverflowError):
        return None


def _timestamp(value, now:datetime) -> float | None:
    if not isinstance(value,datetime) or value.tzinfo is None:
        return None
    return (now-value.astimezone(timezone.utc)).total_seconds()


def _recent(value,now:datetime,limit:int=MAX_AGE_S) -> bool:
    age=_timestamp(value,now)
    return age is not None and 0<=age<limit


def _virtual_open_pnl(position:dict,mark:float) -> float | None:
    """Unrealized PnL less prospective exit fee; entry fee is in cash.

    A short is synthetic here: this is not an exchange margin position.
    """
    if position.get("direction") not in ("LONG","SHORT"):
        return None
    entry=_number(position.get("entry_price"))
    qty=_number(position.get("qty"))
    if entry is None or qty is None or entry<=0 or qty<=0:
        return None
    sign=1 if position["direction"]=="LONG" else -1
    pnl=sign*(mark-entry)*qty - mark*qty*EXIT_FEE_RATE
    return round(pnl,6) if math.isfinite(pnl) else None


def snapshot(cur,now:datetime|None=None) -> dict:
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:raise ValueError("UTC-aware snapshot time required")
    now=now.astimezone(timezone.utc)
    cur.execute(
        "SELECT name, to_regclass('aegis.' || name) AS relation "
        "FROM unnest(%s::text[]) AS tbl(name)",
        (list(REQUIRED),))
    rows=list(cur.fetchall())
    present={r["name"]: r["relation"] is not None for r in rows}
    missing=[table for table in REQUIRED if not present.get(table)]
    if missing:
        return {"ok":True,"initialized":False,"mode":"KRAKEN_PAPER_SOURCE_BACKED",
                "reason":"stream_schema_missing","missing_tables":missing,
                "micro_engine":{"paper_bots":[],"decision_journal":[],
                                "active_intervals_minutes":[]},
                "live_execution_enabled":False}

    cur.execute("SELECT stream_name,state,last_message_at,last_closed_bar,updated_at "
                "FROM aegis.stream_status WHERE stream_name LIKE 'kraken-public-micro-%' "
                "ORDER BY updated_at DESC LIMIT 28")
    sources=list(cur.fetchall())
    latest_sources={}
    for r in sources:
        name=r["stream_name"]
        if name not in latest_sources:latest_sources[name]=r
    fresh_intervals=[n for n in INTERVALS if
                     (p:=latest_sources.get(f"kraken-public-micro-{n}m"))
                     and p.get("state")=="CONNECTED"
                     and _recent(p.get("updated_at"),now)]
    cur.execute("SELECT bar_start,open,high,low,close,volume FROM aegis.stream_candles "
                "WHERE symbol='BTC' AND interval_minutes=1 "
                "ORDER BY bar_start DESC LIMIT 1")
    last_btc=cur.fetchone()
    market=None
    if last_btc:
        observed_at=last_btc["bar_start"] + timedelta(minutes=1)
        price=_number(last_btc.get("close"))
        if _recent(observed_at,now,MAX_AGE_S) and price is not None and price>0:
            market={"symbol":"BTC","currency":"USD","close":price,
                    "bar_end":observed_at,"bar_interval_minutes":1,
                    "price_kind":"PERSISTED_CLOSED_CANDLE","live_tick":False,
                    "source":"Neon / Kraken public OHLC"}
    cur.execute("SELECT agent_id,symbol,interval_minutes,strategy,direction,cash,"
                "peak_equity,max_drawdown,halted,updated_at "
                "FROM aegis.stream_accounts WHERE symbol='BTC' "
                "ORDER BY interval_minutes,strategy,direction LIMIT 120")
    accounts=list(cur.fetchall())
    cur.execute("SELECT agent_id,position_id,symbol,interval_minutes,opened_at,"
                "entry_price,qty,stop_price,target_price,last_mark,direction "
                "FROM aegis.stream_positions WHERE symbol='BTC' "
                "ORDER BY opened_at DESC LIMIT 120")
    positions=list(cur.fetchall())
    cur.execute(
        "SELECT t.agent_id,a.strategy,t.symbol,t.interval_minutes,t.direction AS side,"
        "count(*) AS trades,COALESCE(sum(t.net_pnl),0) AS net_pnl,"
        "COALESCE(sum(t.net_pnl) FILTER(WHERE t.net_pnl>0),0) AS gross_gains,"
        "COALESCE(sum(t.net_pnl) FILTER(WHERE t.net_pnl<0),0) AS gross_losses "
        "FROM aegis.stream_trades t JOIN aegis.stream_accounts a "
        "ON a.agent_id=t.agent_id WHERE t.symbol='BTC' "
        "GROUP BY t.agent_id,a.strategy,t.symbol,t.interval_minutes,t.direction")
    evidence=list(cur.fetchall())
    cur.execute("SELECT agent_id,bar_start,observed_at,symbol,interval_minutes,"
                "strategy,direction,action,reason,reference_price,"
                "position_id,qty,net_pnl FROM aegis.stream_decisions "
                "WHERE symbol='BTC' ORDER BY observed_at DESC LIMIT 36")
    decisions=list(cur.fetchall())
    cur.execute("SELECT agent_id,symbol,interval_minutes,direction,closed_at,"
                "net_pnl,reason,qty,entry_price,exit_price,entry_fee,exit_fee,"
                "slippage_cost,financing_cost FROM aegis.stream_trades "
                "WHERE symbol='BTC' ORDER BY closed_at DESC LIMIT 24")
    last_trades=list(cur.fetchall())
    bots=project_paper_bots(accounts,evidence,positions,fresh_intervals,[])
    bot_by_id={b["bot_id"]:b for b in bots}
    exposure_count=0
    unrealized=0.
    for p in positions:
        b=bot_by_id.get(p.get("agent_id"))
        if not b:continue
        if not market:
            b["open_unrealized_net"]=None
            b["open_mark_source"]="NO_FRESH_MARK"
        else:
            mark=_virtual_open_pnl(p,market["close"])
            b["open_unrealized_net"]=mark
            b["open_mark_source"]="PERSISTED_CLOSED_1M_CANDLE"
            if mark is not None:
                unrealized+=mark
                exposure_count+=1
    activity=max([r["observed_at"] for r in decisions if
                  isinstance(r.get("observed_at"),datetime)],default=None)
    return _json_safe({
        "ok":True,"initialized":True,"mode":"KRAKEN_PAPER_SOURCE_BACKED",
        "generated_at":now,"market":market,
        "micro_engine":{
            "paper_bots":bots,
            "open_positions":positions,
            "decision_journal":decisions,
            "recent_closed_trades":last_trades,
            "sources":sources,
            "active_intervals_minutes":fresh_intervals,
        },
        "pulse":{
            "last_decision_at":activity,
            "open_positions":len(positions),
            "paper_open_unrealized_net":round(unrealized,4) if market and exposure_count else None,
            "marked_positions":exposure_count,
            "caveat":"No cross-account real portfolio: isolated virtual books and costed exit estimates",
        },
        "live_execution_enabled":False,
        "demo_order_execution_enabled":False,
        "paper_only":True,
    })


def get_paper_desk() -> dict:
    with _connect() as conn, conn.cursor() as cur:
        return snapshot(cur)
