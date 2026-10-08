from aegis.stage3 import decide_role, window_stats
from datetime import datetime, timezone, timedelta

def test_shadows_can_never_promote_from_ghost_returns_alone():
    role,risk,status,reason=decide_role(
      research_status="PROBATION",prior_role="SHADOW",forward_days=90,
      trade_count=0,profit_factor=99,net_pnl=5000,drawdown=0,shadow_count=200)
    assert role=="SHADOW" and risk==0
    assert status=="COLLECTING"

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

def test_research_probation_suspends_orders_without_permanent_shadow_lock():
    role,risk,status,_=decide_role(
      research_status="PROBATION",prior_role="ACTIVE_PAPER",forward_days=2,
      trade_count=0,profit_factor=0,net_pnl=0,drawdown=0)
    assert (role,risk,status)==("ACTIVE_PAPER",1,"RESEARCH_HOLD")
    recovered=decide_role(
      research_status="ACTIVE",prior_role=role,forward_days=3,
      trade_count=0,profit_factor=0,net_pnl=0,drawdown=0)
    assert recovered[0]=="ACTIVE_PAPER"

def test_research_gate_can_authorize_new_paper_candidate_only():
    authorized=decide_role(
      research_status="ACTIVE",prior_role="SHADOW",forward_days=2,
      trade_count=0,profit_factor=0,net_pnl=0,drawdown=0)
    assert authorized[0]=="ACTIVE_PAPER"
    assert authorized[2]=="COLLECTING"

def test_costed_shadow_qualifies_for_review_without_paper_allocation():
    role,risk,status,reason=decide_role(
      research_status="PROBATION",prior_role="SHADOW",forward_days=45,
      trade_count=0,profit_factor=0,net_pnl=0,drawdown=0,
      shadow_costed_trades=52,shadow_pf=1.45,shadow_net=420,
      shadow_drawdown=0.018,shadow_days=45)
    assert (role,risk,status)==("CHALLENGER_READY",0,"REVIEW_REQUIRED")

def test_costed_shadow_stress_rejection():
    role,risk,status,_=decide_role(
      research_status="PROBATION",prior_role="SHADOW",forward_days=60,
      trade_count=0,profit_factor=0,net_pnl=0,drawdown=0,
      shadow_costed_trades=100,shadow_pf=1.8,shadow_net=15000,
      shadow_drawdown=0.09,shadow_days=60)
    assert (role,risk,status)==("SHADOW",0,"SHADOW_DRAWDOWN")

def test_shadow_challenger_not_authorized_for_paper():
    role,risk,status,_=decide_role(
      research_status="PROBATION",prior_role="CHALLENGER",forward_days=18,
      trade_count=0,profit_factor=0,net_pnl=0,drawdown=0,
      shadow_costed_trades=18,shadow_pf=1.4,shadow_net=100,
      shadow_drawdown=0.02,shadow_days=18)
    assert (role,risk,status)==("CHALLENGER",0,"COSTED_VALIDATION")
