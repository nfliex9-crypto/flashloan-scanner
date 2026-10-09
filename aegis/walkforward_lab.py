"""Chronological three-fold forward-style historical robustness checking.

Each fold reuses ONLY preceding candles for indicator warmup and enters no
earlier than its own evaluation window. This remains HISTORICAL research:
repeated model selection on these windows invalidates an independent holdout.
No permissions to submit exchange or broker orders.
"""
from __future__ import annotations
from datetime import datetime,timezone
from .backtest_lab import (
    COST_MODES,INTERVALS,load_backtest_bars,simulate_costed_backtest,
    validate_backtest_request,
)
from .directional_signals import classify_horizon

MIN_FOLD_TRADES=5
MIN_PROFIT_FACTOR=1.20
MAX_FOLD_DRAWDOWN_PCT=4.0
REQUIRED_HORIZON_DAYS={"SCALPING":7,"INTRADAY":14,"SWING":60,"POSITION":120}


def verify_walkforward(candles, *, asset:str,strategy:str,interval:str,
                       direction:str,cost_multiplier:float=1.0)->dict:
    n=len(candles)
    if n<180:
        raise ValueError("At least 180 closed bars are required for three nonempty folds")
    first=max(120,int(n*.40))
    remaining=n-first
    bounds=[first, first+remaining//3, first+(remaining*2)//3,n]
    seconds=INTERVALS[interval]
    horizon=classify_horizon(interval)
    windows=[]
    for i in range(3):
        start,end=bounds[i:i+2]
        # Causal prefix: future folds never contribute to an earlier result.
        prefix=candles[:end]
        kwargs={"asset":asset,"strategy":strategy,"interval":interval,
                "direction":direction,"entry_from":start}
        base=simulate_costed_backtest(prefix,**kwargs,
                                      cost_multiplier=cost_multiplier)
        stressed=simulate_costed_backtest(prefix,**kwargs,
                                      cost_multiplier=max(2.,cost_multiplier))
        b=base["stats"]
        s=stressed["stats"]
        base_closed_net=round(sum(x["net_pnl"] for x in base["trades"]),4)
        stress_closed_net=round(sum(x["net_pnl"] for x in stressed["trades"]),4)
        days=(end-start)*seconds/86400
        blockers=[]
        if b["trades"]<MIN_FOLD_TRADES:
            blockers.append("too few closed trades")
        if base_closed_net<=0 or b["profit_factor"]<MIN_PROFIT_FACTOR:
            blockers.append("insufficient after-cost net profit or PF")
        if stress_closed_net<=0:
            blockers.append("fails doubled execution-cost stress")
        if max(b["max_drawdown_pct"],s["max_drawdown_pct"])>=MAX_FOLD_DRAWDOWN_PCT:
            blockers.append("drawdown exceeds research tolerance")
        if days<REQUIRED_HORIZON_DAYS[horizon]:
            blockers.append("too little chronological market coverage")
        windows.append({
            "fold":i+1,"start":datetime.fromtimestamp(candles[start].ts,timezone.utc).isoformat(),
            "end":datetime.fromtimestamp(candles[end-1].ts+seconds,timezone.utc).isoformat(),
            "days":round(days,3),"bars":end-start,"base":b,"stress":s,
            "base_closed_net_pnl":base_closed_net,
            "stress_closed_net_pnl":stress_closed_net,
            "passed":not blockers,"blockers":blockers,
        })
    clean=sum(f["passed"] for f in windows)
    positive=sum(f["base_closed_net_pnl"]>0 for f in windows)
    total_closed=sum(f["base"]["trades"] for f in windows)
    return {
        "ok":True,"mode":"HISTORICAL_WALKFORWARD_ONLY",
        "asset":asset,"strategy":strategy,"interval":interval,
        "horizon":horizon,"direction":direction,"fold_count":3,
        "folds_passed":clean,"positive_folds":positive,
        "closed_trades":total_closed,
        "state":"RESEARCH_ROBUSTNESS_SCREEN_PASSED" if clean==3 else
                "INSUFFICIENT_OR_INCONSISTENT_EVIDENCE",
        "folds":windows,"minimum_days_per_fold":REQUIRED_HORIZON_DAYS[horizon],
        "live_execution_enabled":False,"demo_order_execution_enabled":False,
        "auto_promotion_enabled":False,
        "limitations":[
            "Historical walk-forward windows are NOT untouched real future outcomes.",
            "Repeated selection using these folds creates model-selection bias.",
            "Short borrowing/funding and execution costs are assumptions.",
            "A passing screen cannot authorize demo or real trading orders.",
        ],
    }


def run_walkforward(params:dict,now:datetime|None=None)->dict:
    p=validate_backtest_request(params)
    bars,source=load_backtest_bars(p["asset"],p["interval"],p["bars"],now=now)
    result=verify_walkforward(
        bars,asset=p["asset"],strategy=p["strategy"],interval=p["interval"],
        direction=p["direction"],cost_multiplier=COST_MODES[p["cost"]])
    result["source"]=source
    result["cost_mode"]=p["cost"]
    result["bars"]=len(bars)
    return result
