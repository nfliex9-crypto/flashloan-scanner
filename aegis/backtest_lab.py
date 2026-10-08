"""Source-backed, lookahead-free backtests; never submit broker orders.

Signals are determined at bar close. Entry and flat-signal exits fill at
the NEXT bar open. Stops/targets are checked only after an entered bar opens.
When both touch in one OHLC bar we pessimistically assume the STOP filled first.
Results are research simulations, separate from persisted forward ledger.
"""
from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass,replace
from datetime import datetime,timezone
from typing import Any

from .live_lab import Candle,fetch_ohlc,strategy_positions
from .paper_engine import RiskConfig,_atr_at,_fee,_fill_price,_position_size
from .shadow_broker import conservative_stop_fill

STRATEGIES=("Trend","Momentum","Mean Reversion","Breakout",
            "EMA Cross","RSI Pullback","Channel Breakout")
SYMBOLS=("BTC","XAU")
INTERVALS={"15min":900,"1h":3600}
COST_MODES={"base":1.0,"stress":2.0}
MIN_BARS=120
MAX_BARS=720


def validate_backtest_request(params:dict)->dict:
    allowed={"asset","strategy","interval","cost","bars"}
    if set(params)-allowed:
        raise ValueError("Unsupported backtest parameter")
    asset=params.get("asset","BTC")
    strategy=params.get("strategy","EMA Cross")
    interval=params.get("interval","15min")
    cost=params.get("cost","base")
    bars=params.get("bars","400")
    if asset not in SYMBOLS or strategy not in STRATEGIES:
        raise ValueError("Unsupported asset or strategy")
    if interval not in INTERVALS or cost not in COST_MODES:
        raise ValueError("Unsupported interval or cost model")
    try:
        n=int(bars)
    except (TypeError,ValueError) as exc:
        raise ValueError("Invalid history length") from exc
    if str(n)!=str(bars) or not MIN_BARS<=n<=MAX_BARS:
        raise ValueError("History must be 120–720 candles")
    return {"asset":asset,"strategy":strategy,"interval":interval,
            "cost":cost,"bars":n}


def _parse_td(rows:list[dict])->list[Candle]:
    result={}
    for r in rows:
        dt=datetime.fromisoformat(str(r["datetime"]).replace("Z","+00:00"))
        if dt.tzinfo is None:
            dt=dt.replace(tzinfo=timezone.utc)
        ts=int(dt.astimezone(timezone.utc).timestamp())
        prices=[float(r[k]) for k in ("open","high","low","close")]
        op,hi,lo,close=prices
        if not all(math.isfinite(x) and x>0 for x in prices):
            raise ValueError("Invalid gold candle price")
        if lo>min(op,close) or hi<max(op,close):
            raise ValueError("Inconsistent gold candle")
        if ts in result:
            raise ValueError("Duplicate candle")
        result[ts]=Candle(ts,op,hi,lo,close,float(r.get("volume") or 0))
    return sorted(result.values(),key=lambda bar:bar.ts)


def load_backtest_bars(asset:str,interval:str,bars:int,now:datetime|None=None)->tuple[list[Candle],str]:
    now=now or datetime.now(timezone.utc)
    if asset=="BTC":
        raw=fetch_ohlc("XBTUSD",interval=15 if interval=="15min" else 60)
        source="Kraken XBTUSD OHLC"
    elif asset=="XAU":
        key=os.getenv("TWELVEDATA_API_KEY")
        if not key:
            raise ValueError("Twelve Data gold feed is not configured")
        query=urllib.parse.urlencode({"symbol":"XAU/USD","interval":interval,
            "outputsize":str(bars+2),"timezone":"UTC","apikey":key})
        req=urllib.request.Request(
            "https://api.twelvedata.com/time_series?"+query,
            headers={"User-Agent":"AEGIS-Backtest-Research/1.0"},method="GET")
        try:
            with urllib.request.urlopen(req,timeout=12) as response:
                payload=json.loads(response.read().decode("utf-8"))
        except (urllib.error.HTTPError,urllib.error.URLError,TimeoutError) as exc:
            raise ValueError("Twelve Data historical candles unavailable") from exc
        if not isinstance(payload.get("values"),list):
            raise ValueError("Twelve Data history unavailable for this interval or subscription")
        raw=_parse_td(payload["values"])
        source="Twelve Data XAU/USD historical indicative"
    else:
        raise ValueError("Unsupported asset")
    seconds=INTERVALS[interval]
    clock=now.timestamp()
    # Source may include its currently forming bar. Never trade that bar in
    # a historical result; the nearest complete candle has close <= now.
    closed=[b for b in raw if b.ts+seconds<=clock]
    closed=closed[-bars:]
    if len(closed)<MIN_BARS:
        raise ValueError("Insufficient fully closed candles for backtesting")
    return closed,source


def _stats(trades:list[dict],curve:list[dict],starting_equity:float,open_position:dict|None)->dict:
    wins=sum(t["net_pnl"]>0 for t in trades)
    gains=sum(t["net_pnl"] for t in trades if t["net_pnl"]>0)
    losses=-sum(t["net_pnl"] for t in trades if t["net_pnl"]<0)
    final=curve[-1]["equity"] if curve else starting_equity
    dd=max((x["drawdown"] for x in curve),default=0.0)
    return {"trades":len(trades),"wins":wins,"win_rate":wins/len(trades) if trades else 0.0,
            "net_pnl":round(final-starting_equity,4),
            "return_pct":round((final/starting_equity-1)*100,4),
            "max_drawdown_pct":round(dd*100,4),
            "profit_factor":round(gains/losses,3) if losses else (99.0 if gains else 0.0),
            "fees":round(sum(t["fees"] for t in trades),4),
            "slippage_cost":round(sum(t["slippage_cost"] for t in trades),4),
            "open_position":open_position is not None,
            "ending_equity":round(final,4)}


def simulate_costed_backtest(candles:list[Candle], *,
                             asset:str,strategy:str,interval:str,
                             cost_multiplier:float=1.0,
                             entry_from:int=0,
                             starting_equity:float=100000.0)->dict:
    seconds=INTERVALS[interval]
    if len(candles)<MIN_BARS:
        raise ValueError("Not enough closed candles")
    if any(candles[i].ts>=candles[i+1].ts for i in range(len(candles)-1)):
        raise ValueError("Candle timestamps not strictly increasing")
    cfg=RiskConfig(starting_equity=starting_equity,
        fee_bps_per_side=(3.0 if asset=="XAU" else 3.0)*cost_multiplier,
        slippage_bps_per_side=(5.0 if asset=="XAU" else 2.0)*cost_multiplier)
    positions=strategy_positions([c.close for c in candles],strategy,variant=0)
    cash=starting_equity
    peak=starting_equity
    max_dd=0.0
    circuit_halted=False
    open_pos=None
    trades=[]
    curve=[]
    entries=0
    for i in range(len(candles)):
        bar=candles[i]
        # All decisions at this open are based ONLY on the PREVIOUS closed bar.
        prev_signal=positions[i-1] if i>=1 else 0
        earlier_signal=positions[i-2] if i>=2 else 0
        if open_pos is not None and prev_signal==0 and earlier_signal==1:
            raw_exit=bar.open
            exit_kind="SIGNAL_EXIT"
        else:
            raw_exit=None;exit_kind=None
        if open_pos is None and i>=max(65,entry_from,2) and not circuit_halted:
            if prev_signal==1 and earlier_signal==0:
                entry=_fill_price(bar.open,"BUY",cfg.slippage_bps_per_side)
                atr=_atr_at(candles,i-1)
                stop_gap=max(atr*cfg.atr_stop_multiple,entry*.0025)
                stop=max(.000001,entry-stop_gap)
                target=entry+stop_gap*cfg.reward_to_risk
                equity=max(0,cash)
                qty,_,notional=_position_size(equity,entry,stop,cfg)
                if qty>0 and math.isfinite(qty):
                    fee=_fee(entry*qty,cfg.fee_bps_per_side)
                    cash-=fee
                    open_pos={"entry_index":i,"entry_ts":bar.ts,"entry":entry,
                              "entry_raw":bar.open,"entry_fee":fee,"qty":qty,
                              "stop":stop,"target":target,
                              "entry_slippage":max(0,entry-bar.open)*qty,
                              "notional":notional}
                    entries+=1
        if open_pos is not None and raw_exit is None:
            stop_hit=bar.low<=open_pos["stop"]
            target_hit=bar.high>=open_pos["target"]
            if stop_hit:
                raw_exit=conservative_stop_fill(open_pos["stop"],bar.open)
                exit_kind="STOP_AMBIGUOUS_BAR" if target_hit else "STOP"
            elif target_hit:
                raw_exit=open_pos["target"]
                exit_kind="TARGET"
        if open_pos is not None and raw_exit is not None:
            p=open_pos
            exit_price=_fill_price(raw_exit,"SELL",cfg.slippage_bps_per_side)
            gross=(exit_price-p["entry"])*p["qty"]
            exit_fee=_fee(exit_price*p["qty"],cfg.fee_bps_per_side)
            net=gross-p["entry_fee"]-exit_fee
            cash+=gross-exit_fee
            slip=p["entry_slippage"]+max(0,raw_exit-exit_price)*p["qty"]
            trades.append({"entry_ts":datetime.fromtimestamp(p["entry_ts"],timezone.utc).isoformat(),
                           "exit_ts":datetime.fromtimestamp(
                               bar.ts if exit_kind=="SIGNAL_EXIT" else bar.ts+seconds,
                               timezone.utc).isoformat(),
                           "entry_price":round(p["entry"],6),"exit_price":round(exit_price,6),
                           "qty":round(p["qty"],8),"net_pnl":round(net,4),
                           "fees":round(p["entry_fee"]+exit_fee,4),
                           "slippage_cost":round(slip,4),
                           "reason":exit_kind,"bars_held":i-p["entry_index"]+1})
            open_pos=None
        unrealized=0.0
        if open_pos is not None:
            q=open_pos["qty"]
            unrealized=((bar.close-open_pos["entry"])*q
                        -_fee(bar.close*q,cfg.fee_bps_per_side))
        eq=cash+unrealized
        peak=max(peak,eq)
        dd=1-eq/peak if peak>0 else 0.0
        max_dd=max(max_dd,dd)
        if max_dd>=cfg.max_agent_drawdown_pct:
            circuit_halted=True  # No new orders; existing stop remains managed.
        curve.append({"ts":datetime.fromtimestamp(bar.ts+seconds,timezone.utc).isoformat(),
                      "equity":round(eq,4),"drawdown":round(dd,6)})
    stats=_stats(trades,curve,starting_equity,open_pos)
    return {"stats":stats,"trades":trades,"equity_curve":curve,
            "risk_circuit_halted":circuit_halted,
            "entry_signals_filled":entries,
            "open_position":None if open_pos is None else {
                "entry_ts":datetime.fromtimestamp(open_pos["entry_ts"],timezone.utc).isoformat(),
                "entry_price":round(open_pos["entry"],6),
                "stop":round(open_pos["stop"],6),
                "target":round(open_pos["target"],6),
                "qty":round(open_pos["qty"],8)},
            "parameters":{"risk_per_trade_pct":cfg.risk_per_trade*100,
                "max_position_notional_pct":cfg.max_position_notional_pct*100,
                "max_agent_drawdown_pct":cfg.max_agent_drawdown_pct*100,
                "fee_bps_each_side":cfg.fee_bps_per_side,
                "slippage_bps_each_side":cfg.slippage_bps_per_side}}


def run_backtest(params:dict,now:datetime|None=None)->dict:
    p=validate_backtest_request(params)
    data,source=load_backtest_bars(p["asset"],p["interval"],p["bars"],now=now)
    multiplier=COST_MODES[p["cost"]]
    full=simulate_costed_backtest(data,asset=p["asset"],strategy=p["strategy"],
        interval=p["interval"],cost_multiplier=multiplier)
    split=max(65,int(len(data)*.70))
    holdout=simulate_costed_backtest(data,asset=p["asset"],strategy=p["strategy"],
        interval=p["interval"],cost_multiplier=multiplier,entry_from=split)
    warnings=[]
    if len(holdout["trades"])<20:
        warnings.append("Small out-of-sample trade count: insufficient evidence to trust a profitable result")
    if len(data)<400:
        warnings.append("Short historical window; results can change materially with market regime")
    if p["asset"]=="XAU":
        warnings.append("Gold candles are indicative Twelve Data prices, not executable OANDA quotes")
    warnings.append("This is historical reconstruction, NOT forward paper performance or proof of a profitable strategy")
    return {"ok":True,"mode":"HISTORICAL_BACKTEST_ONLY",
            "live_execution_enabled":False,"source":source,
            "asset":p["asset"],"strategy":p["strategy"],
            "interval":p["interval"],"cost_mode":p["cost"],
            "bars":len(data),"started_at":datetime.fromtimestamp(data[0].ts,timezone.utc).isoformat(),
            "ended_at":datetime.fromtimestamp(data[-1].ts+INTERVALS[p["interval"]],timezone.utc).isoformat(),
            "full":full["stats"],"holdout":holdout["stats"],
            "holdout_start":datetime.fromtimestamp(data[split].ts,timezone.utc).isoformat(),
            "risk_circuit_halted":full["risk_circuit_halted"],
            "last_open_position":full["open_position"],
            "risk_model":full["parameters"],"trades":full["trades"][-75:],
            "equity_curve":full["equity_curve"][-300:],"warnings":warnings}
