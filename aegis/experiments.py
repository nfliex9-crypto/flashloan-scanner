"""Bounded, auditable research experiments; no capital or execution access."""
from __future__ import annotations

import json
from datetime import datetime,timezone
from uuid import uuid4

from .live_lab import evaluate_agent

EXPERIMENT_STRATEGIES=("EMA Cross","RSI Pullback","Channel Breakout")
EXPERIMENT_ASSETS=("BTC","XAU")
MAX_CANDIDATES=6


def validate_controls(data: dict) -> dict:
    if not isinstance(data,dict):
        raise ValueError("Settings must be an object")
    expected={"enabled","assets","strategies","max_candidates"}
    if set(data)!=expected:
        raise ValueError("Expected exactly four research setting fields")
    if not isinstance(data["enabled"],bool):
        raise ValueError("enabled must be boolean")
    if not isinstance(data["assets"],list) or not data["assets"] or len(set(map(str,data["assets"])))!=len(data["assets"]) or any(x not in EXPERIMENT_ASSETS for x in data["assets"]):
        raise ValueError("Select BTC and/or XAU")
    if not isinstance(data["strategies"],list) or not data["strategies"] or len(set(map(str,data["strategies"])))!=len(data["strategies"]) or any(x not in EXPERIMENT_STRATEGIES for x in data["strategies"]):
        raise ValueError("Choose one or more supported experiments")
    n=data["max_candidates"]
    if type(n) is not int or not 1<=n<=MAX_CANDIDATES:
        raise ValueError("max_candidates must be 1 to 6")
    return {"enabled":data["enabled"],"assets":data["assets"],
            "strategies":data["strategies"],"max_candidates":n}


def read_controls(cur)->dict:
    cur.execute(
        "SELECT enabled,assets,strategies,max_candidates,updated_at "
        "FROM aegis.experiment_controls WHERE singleton=TRUE")
    row=cur.fetchone()
    if row is None:
        raise RuntimeError("Experiment controls schema is not initialized")
    return {"enabled":bool(row["enabled"]),"assets":list(row["assets"]),
            "strategies":list(row["strategies"]),
            "max_candidates":int(row["max_candidates"]),
            "updated_at":row["updated_at"]}


def save_controls(data:dict)->dict:
    from .forward_broker import _connect
    c=validate_controls(data)
    with _connect() as conn,conn.cursor() as cur:
        cur.execute(
            "UPDATE aegis.experiment_controls "
            "SET enabled=%s,assets=%s,strategies=%s,max_candidates=%s,updated_at=now() "
            "WHERE singleton=TRUE RETURNING updated_at",
            (c["enabled"],c["assets"],c["strategies"],c["max_candidates"]))
        if not cur.fetchone():
            raise RuntimeError("Experiment controls not installed")
        from .stage3 import emit_event
        emit_event(
            cur,key=f"research-controls:{uuid4().hex}",kind="RESEARCH_CONTROLS",
            scope="RESEARCH",title="Research controls updated",
            description="Shadow candidate selection updated; all broker execution remains disabled",
            payload={"enabled":c["enabled"],"assets":c["assets"],
                     "strategies":c["strategies"],
                     "max_candidates":c["max_candidates"],
                     "live_execution":False})
        saved=read_controls(cur)
        conn.commit()
    return saved


def select_experiment_agents(closed_by_symbol:dict,settings:dict)->list[dict]:
    if not settings["enabled"]:
        return []
    agents=[]
    # Deterministic, bounded selection. No peek at the out-of-sample ranking
    # to choose a backtest winner. Performance gating uses future costed fills.
    for asset in settings["assets"]:
        candles=closed_by_symbol.get(asset)
        if not candles or len(candles)<200:
            continue
        for name in settings["strategies"]:
            if len(agents)>=settings["max_candidates"]:
                return agents
            agent=evaluate_agent(asset,name,candles,variant=0)
            agent["shadow_only"]=True
            agent["experimental"]=True
            agent["research_source"]="closed hourly market bars"
            agents.append(agent)
    return agents


def record_experiments(cur,agents:list[dict],run_id:str,now:datetime)->None:
    from .stage3 import emit_event
    for agent in agents:
        evidence={k:agent[k] for k in ("total_return","oos_return",
            "max_drawdown","profit_factor","sharpe","stress_passes",
            "cost_assumption_bps")}
        evidence.update({"experimental":True,"research_only":True,
            "out_of_sample_note":"Historical OOS is diagnostic; only future costed shadow trades can qualify an agent",
            "live_execution":False})
        cur.execute(
            "INSERT INTO aegis.agent_registry "
            "(agent_id,asset,strategy,generation,status,survival_score,config,evidence,updated_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s) "
            "ON CONFLICT(agent_id) DO UPDATE SET "
            "status=EXCLUDED.status,survival_score=EXCLUDED.survival_score,"
            "evidence=EXCLUDED.evidence,updated_at=EXCLUDED.updated_at",
            (agent["agent_id"],agent["asset"],agent["strategy"],agent["generation"],
             agent["status"],agent["survival_score"],
             json.dumps({"experimental":True,"shadow_only":True,"variant":agent["generation"]}),
             json.dumps(evidence),now))
    emit_event(
        cur,key=f"experiment-review:{run_id}",kind="EXPERIMENT_REVIEW",
        scope="RESEARCH",title=f"{len(agents)} strategy experiments evaluated",
        description="Closed 1h bars, historical OOS tests and future costed shadow fills; no live execution",
        run_id=run_id,at=now,
        payload={"candidate_count":len(agents),"candidate_ids":[a["agent_id"] for a in agents],
                 "live_execution":False})
