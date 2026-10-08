"""Evidence-gated market horizon chooser. No authority to route broker orders.

Only forward-settled costed virtual fills can qualify a candidate.
A historical backtest can inform research but cannot promote a horizon.
Every decision is explicit about small samples, source and uncertainty.
"""
from __future__ import annotations

from datetime import datetime,timezone
from .directional_signals import HORIZONS,classify_horizon

MIN_CLOSED_TRADES=20
MIN_PROFIT_FACTOR=1.25
MAX_ALLOWED_DRAWDOWN=0.04
MIN_SAMPLE_DAYS={"SCALPING":7,"INTRADAY":14,"SWING":60,"POSITION":120}
TIMEFRAME_MINUTES={1:"1min",5:"5min",15:"15min",60:"1h",
                   240:"4h",1440:"1day",10080:"1week"}


def rank_forward_horizons(rows:list[dict], *, side:str="LONG")->dict:
    """Rows from stream ledger are LONG-only until short virtual fills exist."""
    if side not in ("LONG","SHORT","BOTH"):
        raise ValueError("Unsupported side selection")
    options=[]
    for row in rows:
        interval=TIMEFRAME_MINUTES.get(int(row["interval_minutes"]))
        if not interval:
            continue
        horizon=classify_horizon(interval)
        n=int(row.get("trades") or 0)
        gains=float(row.get("gross_gains") or 0)
        losses=abs(float(row.get("gross_losses") or 0))
        pf=(min(99.0,gains/losses) if losses>0 else
            (99.0 if gains>0 else 0.0))
        net=float(row.get("net_pnl") or 0)
        dd=max(0.0,float(row.get("max_drawdown") or 0))
        first=row.get("first_trade")
        latest=row.get("last_trade")
        if isinstance(first,str):
            first=datetime.fromisoformat(first.replace("Z","+00:00"))
        if isinstance(latest,str):
            latest=datetime.fromisoformat(latest.replace("Z","+00:00"))
        duration=0.0
        if first and latest:
            if first.tzinfo is None or latest.tzinfo is None:
                raise ValueError("Forward times must be timezone aware")
            duration=max(0.0,(latest-first).total_seconds()/86400)
        requirements={
            "trades":n>=MIN_CLOSED_TRADES,
            "observation_days":duration>=MIN_SAMPLE_DAYS[horizon],
            "profit_factor":pf>=MIN_PROFIT_FACTOR,
            "net_positive":net>0,
            "drawdown":dd<MAX_ALLOWED_DRAWDOWN,
            "direction_supported":(
                row.get("side","LONG") in ("LONG","SHORT") and
                (side=="BOTH" or side==row.get("side","LONG"))
            ),
        }
        qualified=all(requirements.values())
        # Use costed forward net per trade penalized by drawdown.
        # This is a *relative research score*, not a risk allocation.
        score=net/max(n,1)-dd*1000 if qualified else None
        options.append({
            "asset":row["symbol"],"interval":interval,"horizon":horizon,
            "direction":row.get("side","LONG"),"trades":n,
            "observed_days":round(duration,2),"net_pnl":round(net,4),
            "profit_factor":round(pf,3),"max_drawdown":round(dd,5),
            "qualified":qualified,"failed_checks":[k for k,v in requirements.items() if not v],
            "score":round(score,4) if score is not None else None,
            "execution_authorized":False,
        })
    ready=sorted((r for r in options if r["qualified"]),
                 key=lambda r:(-r["score"],-r["trades"],r["interval"]))
    by_side={direction:next((row for row in ready if row["direction"]==direction),None)
             for direction in ("LONG","SHORT")}
    return {
        "mode":"EVIDENCE_GATED_RESEARCH_ROUTER",
        "direction":side,
        "selected":ready[0] if ready else None,
        "selected_by_direction":by_side,
        "state":"RESEARCH_LEADER_AVAILABLE" if ready else "INSUFFICIENT_FORWARD_EVIDENCE",
        "candidates":options,
        "live_execution_enabled":False,
        "demo_order_execution_enabled":False,
        "selection_is_not_a_trading_order":True,
        "limitations":"Only persisted costed BTC/ETH micro paper fills at 1m/5m/15m qualify today; gold and 4h/daily/weekly need their own forward evidence.",
    }
