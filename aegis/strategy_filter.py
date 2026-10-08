"""Forward-evidence strategy filter. No backtest-only promotions.

Costed real-time shadow results can demote weak strategies from NEW
virtual entries; no automatic live or main-paper capital allocation.
Quarantine is latched until human review (never silently rearmed).
"""
from __future__ import annotations
from datetime import datetime,timezone

MIN_FILTER_TRADES = 20
WEAK_PROFIT_FACTOR = 0.80
MAX_SHADOW_DRAWDOWN = 0.05
MIN_RANK_TRADES = 5


def evaluate_strategy(*, trades: int, net: float, wins: int,
                      profit_factor: float, max_drawdown: float) -> dict:
    n=max(0,int(trades))
    pf=max(0.0,float(profit_factor))
    dd=max(0.0,float(max_drawdown))
    net=float(net)
    if dd >= MAX_SHADOW_DRAWDOWN:
        state,reason="QUARANTINED","5% independent shadow drawdown circuit exceeded"
    elif n >= MIN_FILTER_TRADES and net < 0 and pf < WEAK_PROFIT_FACTOR:
        state,reason="QUARANTINED",f"{n} costed trades; net negative and PF below {WEAK_PROFIT_FACTOR:.2f}"
    elif n < MIN_RANK_TRADES:
        state,reason="COLLECTING",f"Only {n} closed costed trades; not enough forward evidence"
    elif n < MIN_FILTER_TRADES:
        state,reason="OBSERVING",f"{n}/{MIN_FILTER_TRADES} costed trades before risk filter"
    elif net > 0 and pf >= 1.30:
        state,reason="LEADING",f"{n} costed trades; positive net and PF >= 1.30"
    else:
        state,reason="WATCH",f"{n} costed trades; needs better risk-adjusted performance"
    # This score is for display/ranking only; it does not authorize risk.
    score = (min(20.0,n)*0.6 + min(2.0,pf)*20.0 +
             min(20.0,max(-20.0,net/100.0)) - dd*200)
    return {"state":state,"reason":reason,"score":round(score,2),
            "trades":n,"wins":int(wins),"net_pnl":round(net,4),
            "profit_factor":round(pf,3),"max_drawdown":round(dd,6),
            "allow_new_shadow_entry":state!="QUARANTINED",
            "live_execution_enabled":False}


def strategy_snapshot(cur) -> list[dict]:
    """Derive rankings only from persisted virtual fills and equity evidence."""
    cur.execute(
        "SELECT a.agent_id,a.asset,a.strategy,a.status AS research_status,"
        "COALESCE(s.max_drawdown,0) AS max_drawdown,"
        "count(t.trade_id) AS trades,"
        "count(t.trade_id) FILTER(WHERE t.net_pnl>0) AS wins,"
        "COALESCE(sum(t.net_pnl),0) AS net,"
        "COALESCE(sum(t.net_pnl) FILTER(WHERE t.net_pnl>0),0) AS gains,"
        "COALESCE(abs(sum(t.net_pnl) FILTER(WHERE t.net_pnl<0)),0) AS losses "
        "FROM aegis.agent_registry a "
        "LEFT JOIN aegis.shadow_accounts s ON s.agent_id=a.agent_id "
        "LEFT JOIN aegis.shadow_trades t ON t.agent_id=a.agent_id "
        "GROUP BY a.agent_id,a.asset,a.strategy,a.status,s.max_drawdown "
        "ORDER BY a.asset,a.strategy")
    output=[]
    for x in cur.fetchall():
        gains=float(x["gains"]);losses=float(x["losses"])
        pf=min(99.0,gains/losses) if losses>0 else (99.0 if gains>0 else 0.0)
        rank=evaluate_strategy(trades=x["trades"],wins=x["wins"],net=x["net"],
                               profit_factor=pf,max_drawdown=x["max_drawdown"])
        output.append({"agent_id":x["agent_id"],"asset":x["asset"],
                       "strategy":x["strategy"],"research_status":x["research_status"],**rank})
    return sorted(output,key=lambda row:row["score"],reverse=True)


def shadow_entry_allowed(cur, agent_id: str) -> tuple[bool,str]:
    """Fail closed for drawdown/quarantined strategies, even on hourly signals."""
    cur.execute("SELECT max_drawdown FROM aegis.shadow_accounts WHERE agent_id=%s",
                (agent_id,))
    account=cur.fetchone()
    if account is not None and float(account["max_drawdown"]) >= MAX_SHADOW_DRAWDOWN:
        return False,"5% independent shadow drawdown circuit"
    cur.execute(
        "SELECT count(*) AS trades,"
        "COALESCE(sum(net_pnl),0) AS net,"
        "COALESCE(sum(net_pnl) FILTER(WHERE net_pnl>0),0) AS gains,"
        "COALESCE(abs(sum(net_pnl) FILTER(WHERE net_pnl<0)),0) AS losses "
        "FROM aegis.shadow_trades WHERE agent_id=%s",(agent_id,))
    stats=cur.fetchone()
    gains=float(stats["gains"]);losses=float(stats["losses"])
    pf=min(99.0,gains/losses) if losses>0 else (99.0 if gains>0 else 0.0)
    rank=evaluate_strategy(trades=stats["trades"],wins=0,
                           net=stats["net"],profit_factor=pf,
                           max_drawdown=float(account["max_drawdown"]) if account else 0)
    return rank["allow_new_shadow_entry"],rank["reason"]
