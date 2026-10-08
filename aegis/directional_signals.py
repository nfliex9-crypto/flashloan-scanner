"""Causal, directional research signals; no execution or brokerage capabilities.

LONG and SHORT are independently confirmed from a strategy applied to the
observed close and its reciprocal. Flat is preferred on conflicting evidence.
The short signal is NOT a spot sale authorization.
"""
from __future__ import annotations
import math
from .live_lab import strategy_positions

DIRECTIONS=("LONG","SHORT","BOTH")
HORIZONS={
    "SCALPING":("1min","5min"),
    "INTRADAY":("15min","1h"),
    "SWING":("4h","1day"),
    "POSITION":("1week",),
}


def signed_strategy_signals(closes:list[float],strategy:str,direction:str="LONG")->list[int]:
    if direction not in DIRECTIONS:
        raise ValueError("Unsupported directional research mode")
    if any(not math.isfinite(float(p)) or float(p)<=0 for p in closes):
        raise ValueError("Directional input must contain valid positive closes")
    longs=strategy_positions(closes,strategy)
    if direction=="LONG":
        return longs
    # 1/P gives a positive synthetic inverse with no forward prices:
    # breakouts in the reciprocal correspond to downside breakouts in price.
    # The reciprocal is a SIGNAL transformation only, never executable price.
    shorts=strategy_positions([1/float(p) for p in closes],strategy)
    if direction=="SHORT":
        return [-int(s) for s in shorts]
    return [1 if a and not b else (-1 if b and not a else 0)
            for a,b in zip(longs,shorts)]


def classify_horizon(interval:str)->str:
    for family,intervals in HORIZONS.items():
        if interval in intervals:
            return family
    raise ValueError("Unsupported research timeframe")
