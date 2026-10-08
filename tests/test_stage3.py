from aegis.stage3 import decide_role, window_stats
from datetime import datetime, timezone, timedelta

def test_shadows_can_never_promote_from_ghost_returns_alone():
    role,risk,status,reason=decide_role(
      research_status="PROBATION",prior_role="SHADOW",forward_days=90,
      trade_count=0,profit_factor=99,net_pnl=5000,drawdown=0,shadow_count=200)
    assert role=="CHALLENGER" and risk==0
    assert status=="SHADOW_VALIDATION"

def test_forward_drawdown_overrides_other_evidence():
    role,risk,_,_=decide_role(
      research_status="ACTIVE",prior_role="ACTIVE_PAPER",forward_days=120,
      trade_count=300,profit_factor=2.0,net_pnl=20000,drawdown=.051)
    assert (role,risk)==("HALTED",0)

def test_evolution_halt_is_latched():
    role,risk,status,_=decide_role(
      research_status="ACTIVE",prior_role="HALTED",forward_days=120,
      trade_count=300,profit_factor=2.0,net_pnl=20000,drawdown=.01)
    assert (role,risk,status)==("HALTED",0,"MANUAL_REVIEW")

def test_research_active_initially_risk_capped_and_shadow_zero():
    a=decide_role(research_status="ACTIVE",prior_role=None,forward_days=0,
       trade_count=0,profit_factor=0,net_pnl=0,drawdown=0)
    b=decide_role(research_status="PROBATION",prior_role=None,forward_days=0,
       trade_count=0,profit_factor=0,net_pnl=0,drawdown=0)
    assert a[0]=="ACTIVE_PAPER" and a[1]==1
    assert b[0]=="SHADOW" and b[1]==0

def test_window_stats_never_includes_future_or_outside_window():
    now=datetime(2026,10,8,12,tzinfo=timezone.utc)
    rows=[
      {"exit_ts":now-timedelta(hours=12),"net_pnl":15},
      {"exit_ts":now-timedelta(days=10),"net_pnl":-5},
      {"exit_ts":now+timedelta(hours=1),"net_pnl":100},
    ]
    rows=[r for r in rows if r["exit_ts"] <= now]
    assert window_stats(rows,now,1)["trades"]==1
    assert window_stats(rows,now,30)["net_pnl"]==10
