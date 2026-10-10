"""First-class, evidence-backed AEGIS Paper Bot Fleet.

Reuses independent Kraken virtual accounts (one strategy x side x timeframe).
This module has NO broker connection and NO order entry capabilities. New
bots are not created from UI strings; only persisted Neon research accounts
appear. Models can critique bots but cannot promote, trade or set risk limits.
"""
from __future__ import annotations

import math

SUPPORTED = frozenset(("EMA Cross", "Channel Breakout"))
DIRECTIONS = frozenset(("LONG", "SHORT"))
INTERVALS = frozenset((1, 5, 15, 60, 240, 1440, 10080))
MIN_FORWARD_CLOSED = 20


def _finite(value, default=0.0):
    try:
        n=float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return n if math.isfinite(n) else default


def project_paper_bots(accounts: list[dict], evidence: list[dict],
                       positions: list[dict], active_intervals: list[int],
                       research_candidates: list[dict]) -> list[dict]:
    """Create one traceable bot descriptor per existing virtual account.

    Historical OOS or a Grok/JEV opinion never counts as a realized trade.
    Feed freshness and independent OOS eligibility remain separate gates.
    """
    evidence_by_id={r.get("agent_id"):r for r in evidence if isinstance(r,dict)}
    positions_by_id={p.get("agent_id"):p for p in positions if isinstance(p,dict)}
    eligibility_by_id={r.get("agent_id"):r for r in research_candidates
                       if isinstance(r,dict)}
    valid_active=set(n for n in active_intervals if type(n) is int and n in INTERVALS)
    bots=[]
    for a in accounts:
        if not isinstance(a,dict):
            continue
        try:
            interval=int(a["interval_minutes"])
        except (KeyError,TypeError,ValueError,OverflowError):
            continue
        aid=a.get("agent_id")
        if (not isinstance(aid,str) or not aid or a.get("symbol") not in ("BTC","ETH")
                or interval not in INTERVALS or a.get("strategy") not in SUPPORTED
                or a.get("direction") not in DIRECTIONS):
            continue
        row=evidence_by_id.get(aid,{})
        candidate=eligibility_by_id.get(aid,{})
        trade_count=max(0,int(_finite(row.get("trades"),0)))
        realized=_finite(row.get("net_pnl"))
        gains=max(0.0,_finite(row.get("gross_gains")))
        losses=abs(min(0.0,_finite(row.get("gross_losses"))))
        profit_factor=round(gains/losses,4) if losses>0 else None
        average=round(realized/trade_count,6) if trade_count else None
        feed_fresh=interval in valid_active
        risk_halted=a.get("halted") is True
        position=positions_by_id.get(aid)
        qualified=(candidate.get("selection_qualified") is True
                   and trade_count>=MIN_FORWARD_CLOSED and not risk_halted
                   and feed_fresh)
        if risk_halted:
            state="HALTED_RISK"
        elif not feed_fresh:
            state="FEED_UNVERIFIED"
        elif position:
            state="OPEN_PAPER_POSITION"
        elif trade_count==0:
            state="COLLECTING_FORWARD"
        else:
            state="PAPER_OBSERVING"
        bots.append({
            "bot_id":aid,
            "asset":a["symbol"],
            "strategy":a["strategy"],
            "direction":a["direction"],
            "interval_minutes":interval,
            "execution_mode":"KRAKEN_VIRTUAL_PAPER_ONLY",
            "state":state,
            "feed_verified":feed_fresh,
            "risk_halted":risk_halted,
            "paper_position_open":bool(position),
            "closed_trades":trade_count,
            "net_pnl_after_costs":round(realized,6) if trade_count else None,
            "average_net_per_closed_trade":average,
            "profit_factor":profit_factor,
            "profit_factor_defined":losses>0,
            "forward_sample_sufficient":trade_count>=MIN_FORWARD_CLOSED,
            "oos_forward_qualified":qualified,
            "qualification_requires_historical_and_forward_receipts":True,
            "maximum_drawdown":round(max(0.0,_finite(a.get("max_drawdown"))),5),
            "cash":round(_finite(a.get("cash")),4),
            "trade_order_permission":False,
            "account_ref":aid,
        })
    bots.sort(key=lambda b:(b["asset"],b["interval_minutes"],
                            b["strategy"],b["direction"],b["bot_id"]))
    return bots
