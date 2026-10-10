"""Quarter-hour SHADOW risk supervision with no new position entries.

Reads genuine fully closed 15m candles. Stops/targets have conservative gap
fills, and a two-hour adverse-stall time exit is experimental PAPER ONLY.
Existing hourly research signals remain unchanged; no OANDA orders.
"""
from __future__ import annotations
import json
import math
import os
import urllib.parse
import urllib.request
from datetime import datetime,timedelta,timezone

from .live_lab import Candle,fetch_ohlc
from .paper_engine import RiskConfig,_fee
from .shadow_broker import shadow_bar_exit,shadow_exit_result,shadow_id

BAR_SECONDS=900
ADVERSE_TIME_STOP_SECONDS=2*3600
CRYPTO_PAIRS={"BTC":"XBTUSD","ETH":"ETHUSD"}
GOLD_FEE_BPS_PER_SIDE=3.0
GOLD_SLIPPAGE_BPS_PER_SIDE=5.0


def closed_fresh_quarters(candles:list[Candle],now:datetime)->list[Candle]:
    """Require contiguous current and most recent closed 15m bar, no lookahead."""
    if now.tzinfo is None or len(candles)<3:
        raise ValueError("Missing timezone-aware clock or 15m history")
    now_ts=int(now.astimezone(timezone.utc).timestamp())
    latest_start=(now_ts//BAR_SECONDS)*BAR_SECONDS
    ordered=sorted(candles,key=lambda c:c.ts)
    if ordered[-1].ts!=latest_start or ordered[-2].ts!=latest_start-BAR_SECONDS:
        raise ValueError("Stale, future or discontinuous 15m provider data")
    for c in ordered[-3:]:
        if not all(math.isfinite(x) and x>0 for x in
                   (c.open,c.high,c.low,c.close)):
            raise ValueError("Invalid 15m OHLC")
        if c.high<max(c.open,c.close) or c.low>min(c.open,c.close):
            raise ValueError("Inconsistent 15m OHLC")
    return [c for c in ordered[:-1] if c.ts+BAR_SECONDS<=now_ts]


def fetch_quarter_bars(symbol:str,now:datetime)->list[Candle]:
    if symbol in CRYPTO_PAIRS:
        return closed_fresh_quarters(fetch_ohlc(CRYPTO_PAIRS[symbol],interval=15),now)
    if symbol!="XAU":
        raise ValueError("No supported 15m shadow data source")
    key=os.getenv("TWELVEDATA_API_KEY")
    if not key:
        raise ValueError("Gold market feed is not configured")
    query=urllib.parse.urlencode({"symbol":"XAU/USD","interval":"15min",
        "outputsize":"96","timezone":"UTC","apikey":key})
    request=urllib.request.Request("https://api.twelvedata.com/time_series?"+query,
        headers={"User-Agent":"AEGIS-Shadow-Exit-Research/1.0"},method="GET")
    with urllib.request.urlopen(request,timeout=10) as response:
        data=json.loads(response.read().decode("utf-8"))
    if data.get("status")=="error" or not isinstance(data.get("values"),list):
        raise ValueError("Gold 15m feed unavailable or interval unauthorized")
    bars=[]
    for row in data["values"]:
        dt=datetime.fromisoformat(str(row["datetime"]).replace("Z","+00:00"))
        if dt.tzinfo is None:
            dt=dt.replace(tzinfo=timezone.utc)
        bars.append(Candle(ts=int(dt.astimezone(timezone.utc).timestamp()),
            open=float(row["open"]),high=float(row["high"]),
            low=float(row["low"]),close=float(row["close"]),
            volume=float(row.get("volume") or 0)))
    return closed_fresh_quarters(bars,now)


def intrabar_exit_reason(position:dict,bars:list[Candle])->tuple[float,str,datetime]|None:
    """Conservative stop before target, then time stop only if persistently losing."""
    hit=shadow_bar_exit(position,bars,bar_seconds=BAR_SECONDS)
    if hit:
        price,reason,at=hit
        return price,reason+"_15M",at
    opened_at=position["opened_at"]
    eligible=[c for c in bars if datetime.fromtimestamp(c.ts,tz=timezone.utc)>=opened_at]
    if len(eligible)<2:
        return None
    last=eligible[-1]
    at=datetime.fromtimestamp(last.ts+BAR_SECONDS,tz=timezone.utc)
    if (at-opened_at).total_seconds()>=ADVERSE_TIME_STOP_SECONDS:
        entry=float(position["entry_price"])
        if eligible[-1].close<entry and eligible[-2].close<entry:
            return last.close,"ADVERSE_TIME_STOP_2H",at
    return None


def settle_intrabar_shadow(cur, *, run_id:str,now:datetime,
                           closed_by_symbol:dict[str,list[Candle]],
                           config:RiskConfig)->dict:
    """Close existing shadow positions at costed 15m prices, never open anything."""
    from dataclasses import replace
    from .stage3 import emit_event
    stats={"quarter_positions_reviewed":0,"quarter_exits":0,
           "quarter_adverse_time_exits":0,"quarter_mark_updates":0}
    if not closed_by_symbol:
        return stats
    cur.execute("SELECT * FROM aegis.shadow_positions WHERE symbol = ANY(%s) "
                "ORDER BY agent_id FOR UPDATE",(list(closed_by_symbol),))
    positions=list(cur.fetchall())
    for p in positions:
        symbol=p["symbol"];bars=closed_by_symbol.get(symbol) or []
        if not bars:
            continue
        stats["quarter_positions_reviewed"]+=1
        cfg=replace(config,fee_bps_per_side=GOLD_FEE_BPS_PER_SIDE,
            slippage_bps_per_side=GOLD_SLIPPAGE_BPS_PER_SIDE) if symbol=="XAU" else config
        decision=intrabar_exit_reason(p,bars)
        if decision:
            price,reason,at=decision
            result=shadow_exit_result(p,price,cfg)
            trade_id=shadow_id("trade",p["position_id"])
            cur.execute(
                "INSERT INTO aegis.shadow_trades "
                "(trade_id,position_id,agent_id,signal_key,symbol,opened_at,closed_at,"
                "raw_entry,entry_price,exit_price,qty,gross_pnl,entry_fee,exit_fee,"
                "slippage_cost,net_pnl,r_multiple,reason,evidence) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb) "
                "ON CONFLICT(position_id) DO NOTHING RETURNING trade_id",
                (trade_id,p["position_id"],p["agent_id"],p["signal_key"],symbol,p["opened_at"],
                 at,p["raw_entry"],p["entry_price"],result["exit_price"],p["qty"],
                 result["gross"],result["entry_fee"],result["exit_fee"],
                 result["slippage_cost"],result["net_pnl"],result["r_multiple"],reason,
                 json.dumps({"run_id":run_id,"source":"CLOSED_15M_SHADOW_MONITOR",
                   "paper_only":True,"fee_bps_each_side":cfg.fee_bps_per_side,
                   "slippage_bps_each_side":cfg.slippage_bps_per_side,
                   "execution_enabled":False})))
            if cur.fetchone() is None:
                continue
            cur.execute("DELETE FROM aegis.shadow_positions WHERE position_id=%s",
                        (p["position_id"],))
            cur.execute(
                "UPDATE aegis.shadow_accounts SET "
                "cash=cash+%s,realized_pnl=realized_pnl+%s,updated_at=%s "
                "WHERE agent_id=%s",(result["gross"]-result["exit_fee"],
                    result["net_pnl"],now,p["agent_id"]))
            emit_event(cur,key=f"shadow-exit:{trade_id}",kind="SHADOW_EXIT",
                scope="SHADOW",title=f"{symbol} 15m costed shadow exit",
                agent=p["agent_id"],symbol=symbol,amount=result["net_pnl"],
                run_id=run_id,at=now,
                severity="success" if result["net_pnl"]>=0 else "danger",
                description=f"{reason} · verified completed 15m candle; no live order")
            stats["quarter_exits"]+=1
            if reason=="ADVERSE_TIME_STOP_2H":
                stats["quarter_adverse_time_exits"]+=1
        else:
            last=bars[-1]
            mid=last.close
            qty=float(p["qty"])
            unrealized=(mid-float(p["entry_price"]))*qty-_fee(mid*qty,cfg.fee_bps_per_side)
            cur.execute(
                "UPDATE aegis.shadow_positions SET last_mark=%s,unrealized_pnl=%s,"
                "updated_at=%s WHERE position_id=%s",
                (mid,unrealized,now,p["position_id"]))
            cur.execute("SELECT cash,peak_equity,max_drawdown FROM aegis.shadow_accounts "
                        "WHERE agent_id=%s FOR UPDATE",(p["agent_id"],))
            acc=cur.fetchone()
            equity=float(acc["cash"])+unrealized
            peak=max(float(acc["peak_equity"]),equity)
            dd=max(float(acc["max_drawdown"]),
                   1-equity/peak if peak>0 else 0)
            cur.execute(
                "UPDATE aegis.shadow_accounts SET peak_equity=%s,max_drawdown=%s,"
                "updated_at=%s WHERE agent_id=%s",(peak,dd,now,p["agent_id"]))
            stats["quarter_mark_updates"]+=1
    return stats


def settle_intrabar_paper(cur, *, run_id:str, now:datetime,
                          closed_by_symbol:dict[str,list[Candle]],
                          config:RiskConfig)->dict:
    """Risk-only stop/target checks for the MAIN paper account, zero new entries.

    Keeps main trading signals and position sizing anchored to closed 1h bars.
    The experimental two-hour losing-trade time stop is intentionally NOT
    applied to paper-main without separate forward validation.
    """
    from .forward_broker import _close_position
    from .stage3 import emit_event
    stats={"quarter_paper_positions_reviewed":0,"quarter_paper_exits":0}
    symbols=[x for x in closed_by_symbol if x in CRYPTO_PAIRS]
    if not symbols:
        return stats
    cur.execute(
        "SELECT * FROM aegis.paper_positions "
        "WHERE status='OPEN' AND symbol = ANY(%s) "
        "ORDER BY opened_at FOR UPDATE",(symbols,))
    for p in cur.fetchall():
        bars=closed_by_symbol.get(p["symbol"]) or []
        if not bars:
            continue
        stats["quarter_paper_positions_reviewed"]+=1
        decision=shadow_bar_exit(p,bars,bar_seconds=BAR_SECONDS)
        if decision is None:
            continue
        raw_price,reason,exit_at=decision
        recorded=_close_position(cur,p,raw_price,reason+"_15M",exit_at,config)
        emit_event(cur,key=f"paper-exit:{recorded['trade_id']}",kind="PAPER_EXIT",
            scope="PAPER",title=f"{p['symbol']} paper stop/target checked at 15m",
            agent=p["agent_id"],symbol=p["symbol"],amount=recorded["net_pnl"],
            run_id=run_id,at=now,
            severity="success" if recorded["net_pnl"]>=0 else "danger",
            description=f"{reason}_15M · completed candle, virtual fill only")
        stats["quarter_paper_exits"]+=1
    return stats
