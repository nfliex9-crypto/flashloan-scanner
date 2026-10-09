"""Evidence-gated market horizon chooser. No authority to route broker orders.

Only forward-settled costed virtual fills can qualify a candidate.
A historical backtest can inform research but cannot promote a horizon.
Every decision is explicit about small samples, source and uncertainty.
"""
from __future__ import annotations

from datetime import datetime,timezone
import math
import hashlib
import json
from .directional_signals import HORIZONS,classify_horizon

MIN_CLOSED_TRADES=20
MIN_PROFIT_FACTOR=1.25
MAX_ALLOWED_DRAWDOWN=0.04
MIN_SAMPLE_DAYS={"SCALPING":7,"INTRADAY":14,"SWING":60,"POSITION":120}
TIMEFRAME_MINUTES={1:"1min",5:"5min",15:"15min",60:"1h",
                   240:"4h",1440:"1day",10080:"1week"}


def valid_historical_receipt(receipt:dict)->bool:
    """Validate the frozen report as well as its content checksum."""
    try:
        payload={k:v for k,v in receipt.items() if k!='evidence_hash'}
        digest=hashlib.sha256(json.dumps(payload,sort_keys=True,allow_nan=False).encode()).hexdigest()
        base=receipt['holdout'];stress=receipt['stress_holdout']
        return (receipt.get('evidence_hash')==digest
                and receipt.get('historical_screen_passed') is True
                and receipt.get('source')=='Kraken XBTUSD closed historical OHLC'
                and len(receipt['history_hash'])==64
                and base['trades']>=20 and base['closed_net_pnl']>0
                and base['profit_factor']>=MIN_PROFIT_FACTOR
                and stress['closed_net_pnl']>0
                and 0<=base['max_drawdown_pct']<4 and 0<=stress['max_drawdown_pct']<4
                and receipt['holdout_days']>=MIN_SAMPLE_DAYS[classify_horizon(receipt['interval'])]
                and receipt['walkforward']['folds_passed']==3)
    except (KeyError,TypeError,ValueError,OverflowError):
        return False


def rank_forward_horizons(rows:list[dict], *, side:str="LONG",
                          historical_evidence:list[dict]|None=None)->dict:
    """Rank settled virtual trade results by independent strategy, side and timeframe."""
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
        dd=float(row["max_drawdown"]) if row.get("max_drawdown") is not None else None
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
            "valid_costed_metrics":all(math.isfinite(v) for v in (gains,losses,net))
                and gains>=0 and n>=0 and dd is not None
                and math.isfinite(dd) and dd>=0,
            "trades":n>=MIN_CLOSED_TRADES,
            "observation_days":duration>=MIN_SAMPLE_DAYS[horizon],
            "profit_factor":pf>=MIN_PROFIT_FACTOR,
            "net_positive":net>0,
            "drawdown":dd is not None and math.isfinite(dd) and 0<=dd<MAX_ALLOWED_DRAWDOWN,
            "account_active":row.get("halted") is not True,
            "direction_supported":(
                row.get("side","LONG") in ("LONG","SHORT") and
                (side=="BOTH" or side==row.get("side","LONG"))
            ),
        }
        qualified=all(requirements.values())
        # All stream books start with 100,000 simulated USD. Normalize by
        # observation days, not dollars/trade (which rewards slow horizons).
        # Unequal market regimes remain a limitation, not proof of superiority.
        score=100*(net/100000.0-dd)/max(duration,1) if qualified else None
        options.append({
            "agent_id":row.get("agent_id"),"strategy":row.get("strategy"),
            "asset":row["symbol"],"interval":interval,"horizon":horizon,
            "direction":row.get("side","LONG"),"trades":n,
            "observed_days":round(duration,2),"net_pnl":round(net,4) if math.isfinite(net) else None,
            "profit_factor":round(pf,3) if math.isfinite(pf) else None,
            "max_drawdown":round(dd,5) if dd is not None and math.isfinite(dd) else None,
            "qualified":qualified,"failed_checks":[k for k,v in requirements.items() if not v],
            "score":round(score,4) if score is not None else None,
            "execution_authorized":False,
        })
    ready=sorted((r for r in options if r["qualified"]),
                 key=lambda r:(-r["score"],-r["trades"],r["interval"]))
    by_side={direction:next((row for row in ready if row["direction"]==direction),None)
             for direction in ("LONG","SHORT")}
    # A forward leader alone is not an adaptive selection. Require a matching
    # historical receipt evaluated BEFORE this forward cohort began. Caller
    # must supply persisted internal receipts, never request query parameters.
    receipts=historical_evidence or []
    eligible=[]
    for option,source in zip(options,[r for r in rows if int(r["interval_minutes"]) in TIMEFRAME_MINUTES]):
        receipt=next((r for r in receipts if
            r.get("agent_id")==option["agent_id"] and
            r.get("asset")==option["asset"] and
            r.get("strategy")==option["strategy"] and
            r.get("interval")==option["interval"] and
            r.get("direction")==option["direction"]),None)
        oos_ok=False
        if receipt and valid_historical_receipt(receipt):
            try:
                end=datetime.fromisoformat(receipt["evaluated_at"].replace("Z","+00:00"))
                start=source["first_trade"]
                if isinstance(start,str):start=datetime.fromisoformat(start.replace("Z","+00:00"))
                oos_ok=bool(receipt.get("evidence_hash")) and end.tzinfo is not None and end<=start
            except (KeyError,TypeError,ValueError):
                pass
        option["historical_evidence_matched"]=oos_ok
        option["selection_qualified"]=option["qualified"] and oos_ok
        if option["selection_qualified"]:eligible.append(option)
    eligible.sort(key=lambda r:(-r["score"],-r["trades"],r["interval"]))
    return {
        "mode":"EVIDENCE_GATED_RESEARCH_ROUTER",
        "direction":side,
        "selected":eligible[0] if eligible else None,
        "selected_by_direction":{s:next((r for r in eligible if r["direction"]==s),None) for s in ("LONG","SHORT")},
        "forward_leader":ready[0] if ready else None,
        "forward_leaders_by_direction":by_side,
        "state":"RESEARCH_LEADER_AVAILABLE" if eligible else
                "AWAITING_MATCHED_OOS_EVIDENCE" if ready else "INSUFFICIENT_FORWARD_EVIDENCE",
        "candidates":options,
        "live_execution_enabled":False,
        "demo_order_execution_enabled":False,
        "selection_is_not_a_trading_order":True,
        "limitations":"Research only: a frozen matching historical screen must predate forward trades. Source snapshots are not forward fills. Short funding is modeled. Gold requires its own forward ledger; sparse or unequal observation windows cannot prove a universally best timeframe.",
    }
