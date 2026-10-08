"""Stage 3 evidence, guarded allocation and append-only operational events.

Only forward paper fills can qualify a trading strategy; 12h ghost returns are
not interchangeable with executed trades. All changes are virtual capital only.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from .forward_broker import ACCOUNT_ID, _connect, _json_safe, _num


MIN_FORWARD_DAYS = 30
MIN_FORWARD_TRADES = 40
MIN_SHADOW_TRADES = 40
MIN_SHADOW_DAYS = 30
PROMOTION_PF = 1.30
MAX_FORWARD_DRAWDOWN = 0.05


def window_stats(rows: list[dict], now: datetime, days: int | None) -> dict:
    threshold = now - timedelta(days=days) if days else None
    selected = [r for r in rows if r["exit_ts"] <= now and (threshold is None or r["exit_ts"] >= threshold)]
    pnls = [_num(r["net_pnl"]) for r in selected]
    positives = sum(v for v in pnls if v > 0)
    negatives = -sum(v for v in pnls if v < 0)
    return {
        "trades": len(selected),
        "wins": sum(v > 0 for v in pnls),
        "net_pnl": round(sum(pnls), 4),
        "win_rate": sum(v > 0 for v in pnls) / len(pnls) if pnls else 0.0,
        "profit_factor": min(99.0, positives / negatives) if negatives > 0 else (99.0 if positives > 0 else 0.0),
    }


def decide_role(*, research_status: str, prior_role: str | None,
                forward_days: float, trade_count: int, profit_factor: float,
                net_pnl: float, drawdown: float, shadow_count: int = 0,
                shadow_costed_trades: int = 0, shadow_pf: float = 0.0,
                shadow_net: float = 0.0, shadow_drawdown: float = 0.0,
                shadow_days: float = 0.0) -> tuple[str,float,str,str]:
    """Fail-closed promotion gate. No position is ever created by this function."""
    if drawdown >= MAX_FORWARD_DRAWDOWN:
        return ("HALTED", 0.0, "RISK_HALT", "Portfolio forward drawdown >= 5%; capital frozen")
    if prior_role == "HALTED":
        return ("HALTED", 0.0, "MANUAL_REVIEW", "Risk halt is latched; never auto-rearm")
    if research_status == "ACTIVE":
        if trade_count >= 10 and profit_factor < 0.75 and net_pnl < 0:
            return ("HALTED", 0.0, "FORWARD_DEMOTION", "10+ forward trades and PF below 0.75")
        # ACTIVE here means paper-research authorization, not champion status.
        # The research gate remains mandatory on every single entry.
        return ("ACTIVE_PAPER", 1.0, "COLLECTING", "Research gate ACTIVE; paper-only, hard-capped 0.25% per trade")
    if prior_role == "ACTIVE_PAPER":
        # Suspend orders via the independent research-status gate; keep approved
        # paper authorization so it can resume if research improves.
        return ("ACTIVE_PAPER", 1.0, "RESEARCH_HOLD", "Paper authorization retained; execution blocked by research probation")

    # Only costed, persisted, independent forward fills can qualify a shadow
    # strategy for a HUMAN review. No automatic paper-capital promotion.
    if shadow_drawdown >= MAX_FORWARD_DRAWDOWN:
        return ("SHADOW", 0.0, "SHADOW_DRAWDOWN", "Independent costed shadow drawdown exceeded 5%; not eligible")
    if (shadow_days >= MIN_SHADOW_DAYS and
            shadow_costed_trades >= MIN_SHADOW_TRADES and
            shadow_pf >= PROMOTION_PF and shadow_net > 0):
        return ("CHALLENGER_READY", 0.0, "REVIEW_REQUIRED", "Costed shadow evidence passed; human review required before any paper allocation")
    if shadow_costed_trades >= 10:
        return ("CHALLENGER", 0.0, "COSTED_VALIDATION", f"Costed shadow fills: {shadow_costed_trades}/{MIN_SHADOW_TRADES}; paper allocation is zero")
    return ("SHADOW", 0.0, "COLLECTING", f"Costed shadow trades: {shadow_costed_trades}/{MIN_SHADOW_TRADES}; ghost observations {shadow_count} not qualifying")

 
def emit_event(cur, *, key: str, kind: str, title: str,
               description: str = "", scope: str = "SYSTEM",
               agent: str | None = None, symbol: str | None = None,
               severity: str = "info", amount: float | None = None,
               run_id: str | None = None, at: datetime | None = None,
               payload: dict | None = None) -> None:
    cur.execute(
        "INSERT INTO aegis.live_events "
        "(event_key,created_at,event_type,scope,agent_id,symbol,severity,title,description,amount,origin_run_id,payload) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT(event_key) DO NOTHING",
        (key, at or datetime.now(timezone.utc), kind, scope, agent, symbol, severity,
         title, description, amount, run_id, json.dumps(payload or {})),
    )


def review_run(cur, run_id: str, now: datetime, agents: list[dict],
               account: dict, summary: dict) -> None:
    """Run inside the broker's transaction. A failed review rolls the tick back."""
    cur.execute("SELECT COALESCE(max(drawdown),0) AS dd FROM aegis.equity_curve WHERE account_id=%s", (ACCOUNT_ID,))
    historical_dd = _num(cur.fetchone()["dd"])
    circuit = str(account["circuit_state"])
    if circuit == "DRAWDOWN_HALT":
        historical_dd = max(historical_dd, MAX_FORWARD_DRAWDOWN)
    age_days = max(0.0, (now - account["created_at"]).total_seconds() / 86400)

    for agent in agents:
        aid = agent["agent_id"]
        cur.execute("SELECT role FROM aegis.agent_allocations WHERE agent_id=%s", (aid,))
        prior = cur.fetchone()
        previous_role = prior["role"] if prior else None
        cur.execute("SELECT exit_ts,net_pnl FROM aegis.paper_trades WHERE agent_id=%s ORDER BY exit_ts", (aid,))
        trades = list(cur.fetchall())
        cur.execute("SELECT count(*) AS n FROM aegis.ghost_trades WHERE agent_id=%s AND settled_at IS NOT NULL", (aid,))
        ghost_count = int(cur.fetchone()["n"])
        cur.execute(
            "SELECT closed_at AS exit_ts,net_pnl FROM aegis.shadow_trades "
            "WHERE agent_id=%s ORDER BY closed_at",(aid,),
        )
        shadow_trades=list(cur.fetchall())
        cur.execute("SELECT initialized_at,max_drawdown FROM aegis.shadow_accounts WHERE agent_id=%s",(aid,))
        shadow_account=cur.fetchone()
        shadow_days=max(0.0,(now-shadow_account["initialized_at"]).total_seconds()/86400) if shadow_account else 0.0
        shadow_dd=_num(shadow_account["max_drawdown"]) if shadow_account else 0.0
        shadow_windows={name:window_stats(shadow_trades,now,period) for name,period in
                        (("24h",1),("7d",7),("30d",30),("lifetime",None))}
        shadow_lifetime=shadow_windows["lifetime"]
        windows = {name: window_stats(trades, now, period) for name, period in
                   (("24h",1),("7d",7),("30d",30),("lifetime",None))}
        lifetime = windows["lifetime"]
        role, multiplier, review_status, reason = decide_role(
            research_status=("PROBATION" if agent.get("shadow_only") else agent["status"]),
            prior_role=previous_role,
            forward_days=age_days,
            trade_count=lifetime["trades"],
            profit_factor=lifetime["profit_factor"],
            net_pnl=lifetime["net_pnl"],
            drawdown=historical_dd,
            shadow_count=ghost_count,
            shadow_costed_trades=shadow_lifetime["trades"],
            shadow_pf=shadow_lifetime["profit_factor"],
            shadow_net=shadow_lifetime["net_pnl"],
            shadow_drawdown=shadow_dd,
            shadow_days=shadow_days,
        )
        windows["shadow"]={**shadow_windows,"forward_days":round(shadow_days,4),"max_drawdown":shadow_dd,
                           "model":"independent_costed_forward","position_sizing":"0.25% isolated virtual equity"}
        eligible = (
            role == "ACTIVE_PAPER" and age_days >= MIN_FORWARD_DAYS and
            lifetime["trades"] >= MIN_FORWARD_TRADES and
            lifetime["profit_factor"] >= PROMOTION_PF and
            lifetime["net_pnl"] > 0 and historical_dd < MAX_FORWARD_DRAWDOWN
        ) or (role == "CHALLENGER_READY" and review_status == "REVIEW_REQUIRED")
        cur.execute(
            "INSERT INTO aegis.agent_evaluations "
            "(agent_id,run_id,evaluated_at,research_status,role,closed_trades,wins,net_pnl,"
            "profit_factor,max_drawdown,forward_days,eligible,reason,windows) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb) "
            "ON CONFLICT (agent_id,run_id) DO NOTHING",
            (aid,run_id,now,agent["status"],role,lifetime["trades"],lifetime["wins"],
             lifetime["net_pnl"],lifetime["profit_factor"],historical_dd,age_days,eligible,
             reason,json.dumps(windows)),
        )
        cur.execute(
            "INSERT INTO aegis.agent_allocations "
            "(agent_id,role,risk_multiplier,review_status,reason,last_reviewed_run,updated_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(agent_id) DO UPDATE SET "
            "role=EXCLUDED.role,risk_multiplier=EXCLUDED.risk_multiplier,"
            "review_status=EXCLUDED.review_status,reason=EXCLUDED.reason,"
            "last_reviewed_run=EXCLUDED.last_reviewed_run,updated_at=EXCLUDED.updated_at",
            (aid,role,multiplier,review_status,reason,run_id,now),
        )
        if previous_role and previous_role != role:
            key=f"evo:{run_id}:{aid}:{role}"
            cur.execute(
                "INSERT INTO aegis.evolution_events "
                "(event_key,agent_id,created_at,previous_role,next_role,reason,evidence) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT(event_key) DO NOTHING",
                (key,aid,now,previous_role,role,reason,json.dumps(windows["lifetime"])),
            )
            emit_event(cur,key=key,kind="ROLE_CHANGED",title=f"{agent['asset']} {agent['strategy']} → {role}",
                       description=reason,scope="EVOLUTION",agent=aid,symbol=agent["asset"],
                       severity="warning" if role == "HALTED" else "info",run_id=run_id,at=now)

    emit_event(
        cur,key=f"tick:{run_id}",kind="ENGINE_TICK",scope="ENGINE",
        title="Hourly market scan completed",
        description=f"{summary['active_agents']} research-active · {summary['entries']} entries · "
                    f"{summary['exits']} exits · {summary['ghosts']} ghost signals",
        run_id=run_id,at=now,payload={"equity":summary["equity"],
        "circuit":summary["circuit_state"],"live_execution":False},
    )
    cur.execute(
        "SELECT p.order_id,p.agent_id,p.symbol,p.qty,f.fill_price FROM aegis.paper_orders p "
        "JOIN aegis.paper_fills f ON p.order_id=f.order_id AND f.fill_kind='ENTRY' "
        "WHERE p.filled_at=%s",
        (now,),
    )
    for p in cur.fetchall():
        emit_event(cur,key=f"entry:{p['order_id']}",kind="PAPER_ENTRY",scope="TRADE",
                   title=f"{p['symbol']} paper LONG opened",description=f"{p['agent_id']} · paper only",
                   agent=p["agent_id"],symbol=p["symbol"],severity="success",run_id=run_id,at=now,
                   payload={"qty":_num(p["qty"]),"fill":_num(p["fill_price"])})

    cur.execute(
        "SELECT trade_id,agent_id,symbol,net_pnl,exit_reason FROM aegis.paper_trades "
        "WHERE created_at >= %s AND created_at <= now()",
        (now - timedelta(minutes=4),),
    )
    for t in cur.fetchall():
        pnl=_num(t["net_pnl"])
        emit_event(cur,key=f"exit:{t['trade_id']}",kind="PAPER_EXIT",scope="TRADE",
                   title=f"{t['symbol']} paper trade closed",
                   description=f"{t['exit_reason']} · net after fees",
                   agent=t["agent_id"],symbol=t["symbol"],severity="success" if pnl>0 else "danger",
                   amount=pnl,run_id=run_id,at=now)
    cur.execute(
        "SELECT ghost_id,agent_id,symbol,reason FROM aegis.ghost_trades "
        "WHERE created_at >= %s AND created_at <= now()",
        (now - timedelta(minutes=4),),
    )
    for g in cur.fetchall():
        emit_event(cur,key=f"ghost:{g['ghost_id']}",kind="GHOST_CREATED",scope="GHOST",
                   title=f"{g['symbol']} ghost signal observed",description=g["reason"],
                   agent=g["agent_id"],symbol=g["symbol"],run_id=run_id,at=now)
    cur.execute(
        "SELECT ghost_id,agent_id,symbol,forward_return,settled_at "
        "FROM aegis.ghost_trades WHERE settled_at IS NOT NULL ORDER BY settled_at DESC LIMIT 250"
    )
    for ghost in cur.fetchall():
        move = _num(ghost["forward_return"])
        emit_event(cur,key=f"ghost-settled:{ghost['ghost_id']}",
            kind="GHOST_SETTLED",scope="GHOST",
            title=f"{ghost['symbol']} ghost observation settled",
            description=f"12-hour shadow return {move*100:+.2f}%; not an executed paper trade",
            agent=ghost["agent_id"],symbol=ghost["symbol"],
            severity="info",run_id=run_id,at=now,
            payload={"return_12h":move,"settled_market_time":ghost["settled_at"].isoformat()})

    if circuit != "OPEN":
        emit_event(cur,key=f"risk:{run_id}:{circuit}",kind="RISK_HALT",scope="RISK",
                   title="Portfolio risk circuit activated",description=circuit,
                   severity="danger",run_id=run_id,at=now)


def get_stage3_state() -> dict:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM aegis.paper_accounts WHERE account_id=%s", (ACCOUNT_ID,))
        account=cur.fetchone()
        if not account:
            return {"ok":True,"initialized":False,"mode":"FORWARD_ONLY"}

        cur.execute("SELECT * FROM aegis.live_events ORDER BY created_at DESC,event_key DESC LIMIT 55")
        events=list(cur.fetchall())
        cur.execute("SELECT a.agent_id,a.asset,a.strategy,a.generation,a.status,a.survival_score,"
                    "a.evidence,b.role,b.risk_multiplier,b.review_status,b.reason,"
                    "e.windows,e.forward_days,e.closed_trades,e.eligible,e.max_drawdown "
                    "FROM aegis.agent_registry a "
                    "LEFT JOIN aegis.agent_allocations b ON a.agent_id=b.agent_id "
                    "LEFT JOIN LATERAL (SELECT * FROM aegis.agent_evaluations "
                    "WHERE agent_id=a.agent_id ORDER BY evaluated_at DESC LIMIT 1) e ON true "
                    "ORDER BY a.asset,a.strategy")
        agents=list(cur.fetchall())
        cur.execute("SELECT * FROM aegis.paper_positions WHERE status='OPEN' ORDER BY opened_at DESC")
        positions=list(cur.fetchall())
        cur.execute(
            "SELECT a.agent_id,a.initialized_at,a.cash,a.realized_pnl,a.peak_equity,a.max_drawdown,"
            "p.position_id,p.symbol,p.entry_price,p.qty,p.unrealized_pnl "
            "FROM aegis.shadow_accounts a "
            "LEFT JOIN aegis.shadow_positions p ON p.agent_id=a.agent_id"
        )
        shadow_account_rows=list(cur.fetchall())
        shadow_by_agent={r["agent_id"]:r for r in shadow_account_rows}
        cur.execute(
            "SELECT agent_id,count(*) AS trades,"
            "count(*) FILTER(WHERE net_pnl>0) AS wins,"
            "COALESCE(sum(net_pnl),0) AS net_pnl,"
            "COALESCE(sum(net_pnl) FILTER(WHERE closed_at>=now()-interval '7 days'),0) AS week_pnl,"
            "COALESCE(sum(net_pnl) FILTER(WHERE closed_at>=now()-interval '30 days'),0) AS month_pnl "
            "FROM aegis.shadow_trades GROUP BY agent_id"
        )
        shadow_trade_stats={r["agent_id"]:r for r in cur.fetchall()}
        cur.execute("SELECT agent_id,count(*) AS trades,"
                    "count(*) FILTER(WHERE net_pnl>0) AS wins,"
                    "coalesce(sum(net_pnl),0) AS earned,"
                    "coalesce(sum(net_pnl) FILTER(WHERE exit_ts >= date_trunc('day',now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'),0) AS today "
                    "FROM aegis.paper_trades GROUP BY agent_id")
        pay={r["agent_id"]:r for r in cur.fetchall()}
        cur.execute("SELECT ts,equity,realized_pnl,unrealized_pnl,drawdown "
                    "FROM aegis.equity_curve WHERE account_id=%s ORDER BY ts DESC LIMIT 180", (ACCOUNT_ID,))
        curve=list(reversed(cur.fetchall()))
        cur.execute("SELECT run_id,started_at,completed_at,status,summary "
                    "FROM aegis.engine_runs WHERE mode='FORWARD_PAPER' ORDER BY started_at DESC LIMIT 24")
        runs=list(cur.fetchall())
        cur.execute(
            "SELECT run_id,started_at,completed_at,status,market_snapshot,summary "
            "FROM aegis.engine_runs WHERE mode='MARKET_MONITOR' "
            "ORDER BY started_at DESC LIMIT 1")
        last_monitor = cur.fetchone()
        cur.execute("SELECT count(*) AS total,count(*) FILTER(WHERE settled_at IS NULL) AS pending "
                    "FROM aegis.ghost_trades")
        ghosts=cur.fetchone()
        cur.execute("SELECT t.trade_id,t.agent_id,t.symbol,t.entry_ts,t.exit_ts,t.entry_price,t.exit_price,"
                    "t.qty,t.gross_pnl,t.fees,t.slippage_cost,t.net_pnl,t.r_multiple,t.exit_reason,t.evidence,"
                    "o.stop_price,o.target_price,o.metadata AS order_metadata "
                    "FROM aegis.paper_trades t "
                    "LEFT JOIN aegis.paper_orders o ON o.agent_id=t.agent_id AND "
                    "o.symbol=t.symbol AND o.filled_at=t.entry_ts "
                    "ORDER BY t.exit_ts DESC LIMIT 60")
        recent_trades=list(cur.fetchall())
        cur.execute("SELECT ghost_id,agent_id,symbol,signal_ts,signal_price,reason,"
                    "settlement_due_at,settled_at,forward_return "
                    "FROM aegis.ghost_trades ORDER BY signal_ts DESC LIMIT 50")
        recent_ghosts=list(cur.fetchall())
        cur.execute("SELECT agent_id,created_at,previous_role,next_role,reason "
                    "FROM aegis.evolution_events ORDER BY created_at DESC LIMIT 20")
        changes=list(cur.fetchall())
        cur.execute(
            "SELECT symbol,source,source_event_ts,ingested_at,attention_score "
            "FROM aegis.intelligence_snapshots ORDER BY ingested_at DESC LIMIT 18"
        )
        intel_snapshots=list(cur.fetchall())

        # Per-agent, real ledger-based open/close feed. Closed trades produce
        # separate OPEN/CLOSE timeline entries, with no fabricated historical
        # forward fills. This feed is deliberately independent of ghost trades.
        cur.execute(
            "SELECT position_id,agent_id,symbol,opened_at,entry_price,qty,unrealized_pnl "
            "FROM aegis.shadow_positions ORDER BY opened_at DESC LIMIT 60")
        shadow_open_feed=list(cur.fetchall())
        cur.execute(
            "SELECT position_id,agent_id,symbol,opened_at,closed_at,entry_price,"
            "exit_price,qty,net_pnl,entry_fee,exit_fee,slippage_cost,reason "
            "FROM aegis.shadow_trades ORDER BY closed_at DESC LIMIT 75")
        shadow_closed_feed=list(cur.fetchall())
        cur.execute(
            "SELECT position_id,agent_id,symbol,opened_at,entry_price,qty "
            "FROM aegis.paper_positions WHERE status='OPEN' "
            "ORDER BY opened_at DESC LIMIT 30")
        paper_open_feed=list(cur.fetchall())
        cur.execute(
            "SELECT trade_id,agent_id,symbol,entry_ts,exit_ts,entry_price,"
            "exit_price,qty,net_pnl,fees,slippage_cost,exit_reason "
            "FROM aegis.paper_trades ORDER BY exit_ts DESC LIMIT 75")
        paper_closed_feed=list(cur.fetchall())
        from .strategy_filter import strategy_snapshot
        strategy_ranks = strategy_snapshot(cur)
        from .experiments import read_controls
        experiment_controls = read_controls(cur)

        # Independent always-on worker. Empty rows mean NOT DEPLOYED, never
        # spoof a connected WebSocket or mix micro trades with forward paper.
        cur.execute(
            "SELECT stream_name,state,last_message_at,last_closed_bar,updated_at "
            "FROM aegis.stream_status ORDER BY updated_at DESC LIMIT 4")
        micro_sources=list(cur.fetchall())
        cur.execute(
            "SELECT agent_id,symbol,interval_minutes,strategy,cash,"
            "peak_equity,max_drawdown,halted,updated_at "
            "FROM aegis.stream_accounts ORDER BY symbol,interval_minutes,strategy")
        micro_agents=list(cur.fetchall())
        cur.execute(
            "SELECT agent_id,position_id,symbol,interval_minutes,opened_at,"
            "entry_price,qty,stop_price,target_price,last_mark "
            "FROM aegis.stream_positions ORDER BY opened_at DESC LIMIT 20")
        micro_positions=list(cur.fetchall())
        cur.execute(
            "SELECT agent_id,symbol,interval_minutes,opened_at,closed_at,"
            "entry_price,exit_price,qty,entry_fee,exit_fee,slippage_cost,net_pnl,reason "
            "FROM aegis.stream_trades ORDER BY closed_at DESC LIMIT 45")
        micro_trades=list(cur.fetchall())
        cur.execute(
            "SELECT symbol,interval_minutes,max(bar_start) AS last_closed_bar,"
            "count(*) AS collected_bars FROM aegis.stream_candles "
            "WHERE bar_start>=now()-interval '24 hours' "
            "GROUP BY symbol,interval_minutes ORDER BY symbol,interval_minutes")
        micro_bar_stats=list(cur.fetchall())
        cur.execute(
            "SELECT t.symbol,t.interval_minutes,count(*) AS trades,"
            "COALESCE(sum(t.net_pnl),0) AS net_pnl,"
            "COALESCE(sum(t.net_pnl) FILTER(WHERE t.net_pnl>0),0) AS gross_gains,"
            "COALESCE(sum(t.net_pnl) FILTER(WHERE t.net_pnl<0),0) AS gross_losses,"
            "min(t.opened_at) AS first_trade,max(t.closed_at) AS last_trade,"
            "COALESCE(max(a.max_drawdown),0) AS max_drawdown "
            "FROM aegis.stream_trades t "
            "LEFT JOIN aegis.stream_accounts a ON a.agent_id=t.agent_id "
            "GROUP BY t.symbol,t.interval_minutes")
        micro_directional_evidence=list(cur.fetchall())

        # These are BROKER-CONFIRMED DEMO records, never computed shadow
        # paper fills. No login, API key, password or account number is stored.
        cur.execute(
            "SELECT source_id,provider,market,account_type,currency,balance,equity,"
            "open_positions,open_orders,spot_balances,source_of_truth,"
            "last_synced,last_status FROM aegis.demo_account_state "
            "ORDER BY last_synced DESC LIMIT 8")
        demo_accounts=list(cur.fetchall())
        cur.execute(
            "SELECT f.source_id,f.external_id,f.order_id,f.position_id,f.symbol,"
            "f.side,f.entry_kind,f.price,f.qty,f.fee,f.fee_asset,f.net_pnl,"
            "f.executed_at,f.agent_id,s.provider "
            "FROM aegis.demo_fills f JOIN aegis.demo_account_state s ON s.source_id=f.source_id "
            "ORDER BY executed_at DESC LIMIT 60")
        demo_fills=list(cur.fetchall())

    trade_feed=[]
    for p in shadow_open_feed:
        trade_feed.append({
            "id":f"shadow-open:{p['position_id']}",
            "agent_id":p["agent_id"],"symbol":p["symbol"],
            "market":"SHADOW","action":"OPEN","state":"OPEN",
            "timestamp":p["opened_at"],"entry_price":_num(p["entry_price"]),
            "qty":_num(p["qty"]),"unrealized_pnl":_num(p["unrealized_pnl"]),
            "realized_net_pnl":None,"source":"PERSISTED_SHADOW_POSITION",
        })
    for p in shadow_closed_feed:
        base={"agent_id":p["agent_id"],"symbol":p["symbol"],
              "market":"SHADOW","state":"CLOSED",
              "qty":_num(p["qty"]),"entry_price":_num(p["entry_price"]),
              "exit_price":_num(p["exit_price"]),"realized_net_pnl":_num(p["net_pnl"]),
              "fee_total":_num(p["entry_fee"])+_num(p["exit_fee"]),
              "slippage_cost":_num(p["slippage_cost"]),
              "reason":p["reason"],"source":"COSTED_SHADOW_LEDGER"}
        trade_feed.append({**base,"id":f"shadow-entry:{p['position_id']}",
                           "action":"OPEN","timestamp":p["opened_at"]})
        trade_feed.append({**base,"id":f"shadow-close:{p['position_id']}",
                           "action":"CLOSE","timestamp":p["closed_at"]})
    for p in paper_open_feed:
        trade_feed.append({
            "id":f"paper-open:{p['position_id']}",
            "agent_id":p["agent_id"],"symbol":p["symbol"],
            "market":"PAPER","action":"OPEN","state":"OPEN",
            "timestamp":p["opened_at"],"entry_price":_num(p["entry_price"]),
            "qty":_num(p["qty"]),"realized_net_pnl":None,
            "source":"PERSISTED_PAPER_POSITION",
        })
    for p in paper_closed_feed:
        base={"agent_id":p["agent_id"],"symbol":p["symbol"],
              "market":"PAPER","state":"CLOSED",
              "qty":_num(p["qty"]),"entry_price":_num(p["entry_price"]),
              "exit_price":_num(p["exit_price"]),"realized_net_pnl":_num(p["net_pnl"]),
              "fee_total":_num(p["fees"]),"slippage_cost":_num(p["slippage_cost"]),
              "reason":p["exit_reason"],"source":"PAPER_FILL_LEDGER"}
        trade_feed.append({**base,"id":f"paper-entry:{p['trade_id']}",
                           "action":"OPEN","timestamp":p["entry_ts"]})
        trade_feed.append({**base,"id":f"paper-close:{p['trade_id']}",
                           "action":"CLOSE","timestamp":p["exit_ts"]})
    trade_feed.sort(key=lambda row:row["timestamp"],reverse=True)
    trade_feed=trade_feed[:180]
    rank_by_id={r["agent_id"]:r for r in strategy_ranks}
    required_micro_feeds={"kraken-public-micro-1m","kraken-public-micro-5m",
                          "kraken-public-micro-15m"}
    live_feeds=set()
    checked_at=datetime.now(timezone.utc)
    for source in micro_sources:
        age=(checked_at-source["updated_at"]).total_seconds() if source["updated_at"] else float("inf")
        if source["stream_name"] in required_micro_feeds and (
            source["state"]=="CONNECTED" and 0<=age<180):
            live_feeds.add(source["stream_name"])
    stream_active=required_micro_feeds.issubset(live_feeds)
    micro_mode=("CONNECTED_PUBLIC_MARKET_PAPER_ONLY" if stream_active else
                "PARTIAL_OR_STALE_PUBLIC_FEEDS" if micro_sources else "WORKER_NOT_DEPLOYED")
    linked_demo_accounts=[]
    for account in demo_accounts:
        a=dict(account)
        age=(checked_at-a["last_synced"]).total_seconds() if a.get("last_synced") else float("inf")
        a["sync_status"]="SYNCED_DEMO" if 0<=age<300 else "STALE_DEMO_HISTORY"
        linked_demo_accounts.append(a)
    demo_broker_state={
        "mode":"NATIVE_DEMO_EXECUTION_HISTORY",
        "live_execution_enabled":False,
        "connected_accounts":linked_demo_accounts,
        "recent_fills":demo_fills,
        "missing_connectors":[name for name in ("MT5_DEMO","BINANCE_SPOT_DEMO")
                              if name not in {a["provider"] for a in demo_accounts}],
        "execution_authorized":False,
        "history_source":"Broker demo / exchange demo. Neon contains only compact reconciled execution IDs.",
    }
    from .horizon_selector import rank_forward_horizons
    micro_horizon_router=rank_forward_horizons(micro_directional_evidence,side="LONG")
    micro_engine={
        "mode":micro_mode,"is_connected":stream_active,
        "source":"Kraken public Spot WebSocket v2 (BTC/ETH only)",
        "live_execution_enabled":False,
        "sources":micro_sources,
        "active_intervals_minutes":[n for n in (1,5,15) if f"kraken-public-micro-{n}m" in live_feeds],
        "agents":micro_agents,
        "open_positions":micro_positions,
        "recent_closed_trades":micro_trades,
        "bar_stats":micro_bar_stats,
        "risk_model":"0.25% budgeted stop risk · 20% notional cap · 5% circuit",
    }

    workers=[]
    for a in agents:
        a=dict(a)
        stats=pay.get(a["agent_id"],{})
        shadow=shadow_by_agent.get(a["agent_id"],{})
        shadow_stats=shadow_trade_stats.get(a["agent_id"],{})
        a.update({"paper_trades":int(stats.get("trades",0)),
                  "paper_wins":int(stats.get("wins",0)),
                  "earned":_num(stats.get("earned",0)),
                  "today":_num(stats.get("today",0)),
                  "shadow_trades":int(shadow_stats.get("trades",0)),
                  "shadow_wins":int(shadow_stats.get("wins",0)),
                  "shadow_net_pnl":_num(shadow_stats.get("net_pnl",0)),
                  "shadow_week_pnl":_num(shadow_stats.get("week_pnl",0)),
                  "shadow_month_pnl":_num(shadow_stats.get("month_pnl",0)),
                  "shadow_max_drawdown":_num(shadow.get("max_drawdown",0)),
                  "shadow_open":bool(shadow.get("position_id")),
                  "shadow_unrealized":_num(shadow.get("unrealized_pnl",0)),
                  "shadow_started_at":shadow.get("initialized_at"),
                  "strategy_filter":rank_by_id.get(a["agent_id"])})
        workers.append(a)
    last=runs[0] if runs else None
    curve_last=curve[-1] if curve else None
    return _json_safe({
        "ok":True,"initialized":True,"mode":"FORWARD_ONLY",
        "generated_at":datetime.now(timezone.utc),
        "vault":{"starting_equity":_num(account["starting_equity"]),
                 "equity":_num(curve_last["equity"]) if curve_last else _num(account["cash"]),
                 "realized":_num(account["realized_pnl"]),
                 "unrealized":_num(curve_last["unrealized_pnl"]) if curve_last else 0,
                 "drawdown":_num(curve_last["drawdown"]) if curve_last else 0,
                 "circuit":account["circuit_state"],
                 "today":sum(w["today"] for w in workers)},
        "workers":workers,"positions":positions,"events":events,
        "equity_curve":curve,"runs":runs,"ghosts":ghosts,
        "evolution_events":changes,"intel_snapshots":intel_snapshots,
        "recent_trades":recent_trades,"recent_ghosts":recent_ghosts,
        "trade_feed":trade_feed,"strategy_rankings":strategy_ranks,
        "experiment_controls":experiment_controls,
        "micro_engine":micro_engine,
        "research_horizon_router":micro_horizon_router,
        "demo_brokers":demo_broker_state,
        "experiment_eligible_shadow_agents":sum(1 for a in agents if a["strategy"] in ("EMA Cross","RSI Pullback","Channel Breakout")),
        "shadow_open_positions":sum(bool(r.get("position_id")) for r in shadow_account_rows),
        "shadow_costed_trades":sum(int(v.get("trades",0)) for v in shadow_trade_stats.values()),
        "last_run":last,"last_market_monitor":last_monitor,
        "engine_frequency":"MARKET_CHECK_EVERY_15M__STRATEGY_BARS_1H",
        "live_money":False,
        "promotion_rules":{"min_forward_days":MIN_FORWARD_DAYS,
            "min_costed_trades":MIN_FORWARD_TRADES,"min_pf":PROMOTION_PF,
            "max_drawdown":MAX_FORWARD_DRAWDOWN,
            "shadow_requires_costed_fills":True},
    })
