from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row

from .live_lab import ASSETS, evaluate_agent, fetch_ohlc, strategy_positions
from .paper_engine import RiskConfig, _atr_at, _fee, _fill_price, _position_size, _signal_reason


ACCOUNT_ID = "paper-main"
STRATEGIES = ("Trend", "Momentum", "Mean Reversion", "Breakout")
MAX_TOTAL_NOTIONAL_PCT = 0.35
PORTFOLIO_MAX_DRAWDOWN_PCT = 0.05
DAILY_LOSS_LIMIT_PCT = 0.01
MAX_CONCURRENT_POSITIONS = 2


def _id(prefix: str, *parts: object) -> str:
    raw = "|".join(str(p) for p in parts).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(raw).hexdigest()[:24]}"


def _dt(ts: int | float) -> datetime:
    return datetime.fromtimestamp(float(ts), tz=timezone.utc)


def _monitor_slot_id(scheduled_at: datetime) -> str:
    """Idempotent, UTC quarter-hour observation ID; not a trade run ID."""
    if scheduled_at.tzinfo is None:
        raise ValueError("Market monitoring timestamps must be timezone-aware")
    return f"monitor:{int(scheduled_at.timestamp() // 900)}"


def _num(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


def _connect():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not configured")
    return psycopg.connect(url, row_factory=dict_row, connect_timeout=10)


def _mark_equity(account: dict, positions: list[dict], live_by_symbol: dict, config: RiskConfig) -> dict:
    unrealized = 0.0
    total_notional = 0.0
    for p in positions:
        mark = live_by_symbol[p["symbol"]].close
        qty = _num(p["qty"])
        entry = _num(p["entry_price"])
        unrealized += (mark - entry) * qty - _fee(mark * qty, config.fee_bps_per_side)
        total_notional += mark * qty
    cash = _num(account["cash"])
    return {
        "cash": cash,
        "unrealized": unrealized,
        "equity": cash + unrealized,
        "total_notional": total_notional,
    }


def _open_positions(cur) -> list[dict]:
    cur.execute(
        "SELECT * FROM aegis.paper_positions "
        "WHERE account_id=%s AND status='OPEN' ORDER BY opened_at",
        (ACCOUNT_ID,),
    )
    return list(cur.fetchall())


def _account(cur) -> dict:
    cur.execute("SELECT * FROM aegis.paper_accounts WHERE account_id=%s", (ACCOUNT_ID,))
    row = cur.fetchone()
    if not row:
        raise RuntimeError("paper account missing")
    return row


def _close_position(
    cur,
    position: dict,
    raw_exit: float,
    reason: str,
    exit_ts: datetime,
    config: RiskConfig,
) -> dict:
    cur.execute(
        "SELECT fee,slippage_cost FROM aegis.paper_fills "
        "WHERE order_id=%s AND fill_kind='ENTRY' ORDER BY fill_ts ASC LIMIT 1",
        (position["position_id"],),
    )
    entry_fill = cur.fetchone() or {"fee": 0, "slippage_cost": 0}

    qty = _num(position["qty"])
    entry = _num(position["entry_price"])
    stop = _num(position["stop_price"])
    exit_price = _fill_price(raw_exit, "SELL", config.slippage_bps_per_side)
    gross = (exit_price - entry) * qty
    exit_fee = _fee(exit_price * qty, config.fee_bps_per_side)
    exit_slippage = max(0.0, raw_exit - exit_price) * qty
    entry_fee = _num(entry_fill["fee"])
    entry_slippage = _num(entry_fill["slippage_cost"])
    net = gross - entry_fee - exit_fee
    risk = max((entry - stop) * qty, 1e-9)

    fill_id = _id("fillx", position["position_id"], exit_ts.isoformat(), reason)
    trade_id = _id("trade", position["position_id"], exit_ts.isoformat(), reason)

    cur.execute(
        "INSERT INTO aegis.paper_fills"
        "(fill_id,order_id,fill_kind,fill_ts,fill_price,qty,fee,slippage_cost,metadata) "
        "VALUES (%s,%s,'EXIT',%s,%s,%s,%s,%s,%s::jsonb) "
        "ON CONFLICT (fill_id) DO NOTHING",
        (
            fill_id,
            position["position_id"],
            exit_ts,
            exit_price,
            qty,
            exit_fee,
            exit_slippage,
            json.dumps({"exit_reason": reason}),
        ),
    )
    cur.execute(
        "INSERT INTO aegis.paper_trades"
        "(trade_id,account_id,agent_id,symbol,side,entry_ts,exit_ts,entry_price,exit_price,qty,"
        "gross_pnl,fees,slippage_cost,net_pnl,r_multiple,exit_reason,evidence) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb) "
        "ON CONFLICT (trade_id) DO NOTHING",
        (
            trade_id,
            position["account_id"],
            position["agent_id"],
            position["symbol"],
            position["side"],
            position["opened_at"],
            exit_ts,
            entry,
            exit_price,
            qty,
            gross,
            entry_fee + exit_fee,
            entry_slippage + exit_slippage,
            net,
            net / risk,
            reason,
            json.dumps(
                {
                    "source": "FORWARD_PAPER",
                    "conservative_ambiguous_bar": reason == "STOP_AMBIGUOUS_BAR",
                }
            ),
        ),
    )
    cur.execute(
        "UPDATE aegis.paper_orders SET status='CLOSED',closed_at=%s WHERE order_id=%s",
        (exit_ts, position["position_id"]),
    )
    cur.execute("DELETE FROM aegis.paper_positions WHERE position_id=%s", (position["position_id"],))
    cur.execute(
        "UPDATE aegis.paper_accounts "
        "SET cash=cash+%s-%s,realized_pnl=realized_pnl+%s,updated_at=now() "
        "WHERE account_id=%s",
        (gross, exit_fee, net, ACCOUNT_ID),
    )
    cur.execute(
        "INSERT INTO aegis.audit_events"
        "(event_key,entity_type,entity_id,event_type,occurred_at,payload) "
        "VALUES (%s,'position',%s,'POSITION_CLOSED',%s,%s::jsonb) "
        "ON CONFLICT (event_key) DO NOTHING",
        (
            f"close:{trade_id}",
            position["position_id"],
            exit_ts,
            json.dumps({"raw_exit": raw_exit, "exit_price": exit_price, "reason": reason, "net_pnl": net}),
        ),
    )
    return {"trade_id": trade_id, "net_pnl": net, "exit_reason": reason}


def run_forward_tick(scheduled_at: datetime | None = None, config: RiskConfig | None = None) -> dict:
    config = config or RiskConfig()
    scheduled_at = scheduled_at or datetime.now(timezone.utc)
    if scheduled_at.tzinfo is None:
        scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)
    else:
        scheduled_at = scheduled_at.astimezone(timezone.utc)

    all_by_symbol = {symbol: fetch_ohlc(pair) for symbol, pair in ASSETS.items()}
    closed_by_symbol = {symbol: candles[:-1] for symbol, candles in all_by_symbol.items()}
    live_by_symbol = {symbol: candles[-1] for symbol, candles in all_by_symbol.items()}
    latest_closed = {symbol: candles[-1].ts for symbol, candles in closed_by_symbol.items()}
    run_id = f"forward:{latest_closed['BTC']}:{latest_closed['ETH']}"
    # Gold uses independently timestamped Twelve Data candles and must never
    # delay/disable existing crypto paper trading when its provider fails.
    gold_closed = None
    gold_live = None
    gold_research_agents = []
    gold_status = "UNAVAILABLE"
    gold_reason = None
    try:
        from .gold_lab import fetch_gold_research, gold_agents
        gold_closed, gold_live = fetch_gold_research(scheduled_at)
        gold_research_agents = gold_agents(gold_closed)
        gold_status = "CLOSED_BAR_READY"
    except (ValueError, KeyError, TypeError, OSError) as exc:
        gold_status = "STALE_OR_FEED_ERROR"
        gold_reason = str(exc)[:120]


    summary = {
        "entries": 0,
        "exits": 0,
        "ghosts": 0,
        "settled_ghosts": 0,
        "live_execution": False,
    }

    with _connect() as conn:
        with conn.cursor() as cur:
            # Quarter-hour monitoring is separate from the 1h trading strategy.
            # A heartbeat never opens/closes a position or reprocesses an hourly bar.
            monitor_id = _monitor_slot_id(scheduled_at)
            monitor_snapshot = {
                "observation_type": "PARTIAL_HOURLY_CANDLE_SNAPSHOT",
                "crypto": {
                    symbol: {"source": "Kraken OHLC open 1h bar",
                             "bar_started_at": _dt(candle.ts).isoformat(),
                             "sampled_at": scheduled_at.isoformat(),
                             "observed_close": candle.close}
                    for symbol, candle in live_by_symbol.items()
                },
                "gold": {
                    "source": "Twelve Data XAU/USD open 1h bar",
                    "available": gold_live is not None,
                    "bar_started_at": _dt(gold_live.ts).isoformat() if gold_live else None,
                    "observed_close": gold_live.close if gold_live else None,
                    "status": gold_status,
                },
                "paper_trading_15min": False,
                "live_execution": False,
            }
            # Snapshot empirical strategy standings on each genuine 15m pulse.
            # Rankings never authorize positions; only closed costed fills count.
            from .strategy_filter import strategy_snapshot
            current_rankings = strategy_snapshot(cur)
            monitor_snapshot["strategy_rankings"] = current_rankings
            monitor_summary = {
                "cadence_minutes": 15,
                "filter_checked_at": scheduled_at.isoformat(),
                "agents_ranked": len(current_rankings),
                "quarantined": sum(x["state"] == "QUARANTINED" for x in current_rankings),
                "no_order_execution": True,
                "real_money": False,
            }
            cur.execute(
                "INSERT INTO aegis.engine_runs"
                "(run_id,started_at,completed_at,mode,status,market_snapshot,summary) "
                "VALUES (%s,%s,now(),'MARKET_MONITOR','COMPLETED',%s::jsonb,%s::jsonb) "
                "ON CONFLICT (run_id) DO NOTHING",
                (monitor_id, scheduled_at, json.dumps(monitor_snapshot),
                 json.dumps(monitor_summary)),
            )
            cur.execute(
                "INSERT INTO aegis.engine_runs(run_id,started_at,mode,status,market_snapshot) "
                "VALUES (%s,%s,'FORWARD_PAPER','RUNNING',%s::jsonb) "
                "ON CONFLICT (run_id) DO NOTHING RETURNING run_id",
                (run_id, scheduled_at, json.dumps({"latest_closed": latest_closed})),
            )
            if cur.fetchone() is None:
                cur.execute("SELECT status,summary FROM aegis.engine_runs WHERE run_id=%s", (run_id,))
                prior = cur.fetchone()
                # Keep the real market-monitor heartbeat, but never duplicate
                # forward fills or change strategy state for a repeated 1h bar.
                conn.commit()
                return {
                    "ok": True,
                    "monitor_id": monitor_id,
                    "monitor_only": True,
                    "run_id": run_id,
                    "idempotent_noop": True,
                    "prior": _json_safe(prior),
                }

            cur.execute(
                "INSERT INTO aegis.paper_accounts"
                "(account_id,name,currency,starting_equity,cash,realized_pnl,peak_equity,circuit_state) "
                "VALUES (%s,'AEGIS Forward Paper','USD',%s,%s,0,%s,'OPEN') "
                "ON CONFLICT (account_id) DO NOTHING",
                (ACCOUNT_ID, config.starting_equity, config.starting_equity, config.starting_equity),
            )

            account = _account(cur)
            today = scheduled_at.date()
            circuit = str(account["circuit_state"])
            if circuit.startswith("DAILY_HALT:") and circuit != f"DAILY_HALT:{today.isoformat()}":
                cur.execute(
                    "UPDATE aegis.paper_accounts SET circuit_state='OPEN',updated_at=now() "
                    "WHERE account_id=%s",
                    (ACCOUNT_ID,),
                )
                circuit = "OPEN"

            agents = []
            for symbol, candles in closed_by_symbol.items():
                for idx, strategy in enumerate(STRATEGIES):
                    agent = evaluate_agent(symbol, strategy, candles, variant=idx % 2)
                    agents.append(agent)
                    cur.execute(
                        "INSERT INTO aegis.agent_registry"
                        "(agent_id,asset,strategy,generation,status,survival_score,config,evidence,updated_at) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,now()) "
                        "ON CONFLICT (agent_id) DO UPDATE SET "
                        "status=EXCLUDED.status,survival_score=EXCLUDED.survival_score,"
                        "evidence=EXCLUDED.evidence,updated_at=now()",
                        (
                            agent["agent_id"],
                            agent["asset"],
                            agent["strategy"],
                            agent["generation"],
                            agent["status"],
                            agent["survival_score"],
                            json.dumps({"variant": agent["generation"]}),
                            json.dumps(
                                {
                                    "total_return": agent["total_return"],
                                    "oos_return": agent["oos_return"],
                                    "max_drawdown": agent["max_drawdown"],
                                    "profit_factor": agent["profit_factor"],
                                    "sharpe": agent["sharpe"],
                                    "stress_passes": agent["stress_passes"],
                                }
                            ),
                        ),
                    )

            positions = _open_positions(cur)
            for position in positions:
                candles = closed_by_symbol[position["symbol"]]
                opened_at = position["opened_at"].astimezone(timezone.utc)
                exit_event = None

                for bar in candles:
                    bar_open = _dt(bar.ts)
                    bar_close = bar_open + timedelta(hours=1)
                    # Never use pre-entry OHLC from the candle in which the fill occurred.
                    # We intentionally start stop/target evaluation from the next full candle.
                    if bar_open < opened_at:
                        continue
                    stop_hit = bar.low <= _num(position["stop_price"])
                    target_hit = bar.high >= _num(position["target_price"])
                    if stop_hit and target_hit:
                        exit_event = (_num(position["stop_price"]), "STOP_AMBIGUOUS_BAR", bar_close)
                        break
                    if stop_hit:
                        exit_event = (_num(position["stop_price"]), "STOP", bar_close)
                        break
                    if target_hit:
                        exit_event = (_num(position["target_price"]), "TARGET", bar_close)
                        break

                if exit_event is None:
                    agent = next((a for a in agents if a["agent_id"] == position["agent_id"]), None)
                    if agent and agent["latest_signal"] == "FLAT":
                        exit_event = (
                            live_by_symbol[position["symbol"]].close,
                            "SIGNAL_EXIT",
                            scheduled_at,
                        )

                if exit_event:
                    _close_position(cur, position, *exit_event, config)
                    summary["exits"] += 1

            account = _account(cur)
            positions = _open_positions(cur)
            marks = _mark_equity(account, positions, live_by_symbol, config)
            peak = max(_num(account["peak_equity"]), marks["equity"])
            drawdown = 1.0 - marks["equity"] / peak if peak > 0 else 0.0

            day_start = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)
            cur.execute(
                "SELECT COALESCE(sum(net_pnl),0) AS pnl FROM aegis.paper_trades "
                "WHERE account_id=%s AND exit_ts >= %s AND exit_ts < %s",
                (ACCOUNT_ID, day_start, day_start + timedelta(days=1)),
            )
            daily_pnl = _num(cur.fetchone()["pnl"])

            if drawdown >= PORTFOLIO_MAX_DRAWDOWN_PCT:
                circuit = "DRAWDOWN_HALT"
            elif daily_pnl <= -config.starting_equity * DAILY_LOSS_LIMIT_PCT:
                circuit = f"DAILY_HALT:{today.isoformat()}"

            cur.execute(
                "UPDATE aegis.paper_accounts SET circuit_state=%s,peak_equity=%s,updated_at=now() "
                "WHERE account_id=%s",
                (circuit, peak, ACCOUNT_ID),
            )

            open_keys = {(p["agent_id"], p["symbol"]) for p in positions}

            for agent in agents:
                closes = [c.close for c in closed_by_symbol[agent["asset"]]]
                signal_positions = strategy_positions(
                    closes,
                    agent["strategy"],
                    agent["generation"],
                )
                if len(signal_positions) < 2:
                    continue
                entry_transition = signal_positions[-1] == 1 and signal_positions[-2] == 0
                if not entry_transition:
                    continue

                closed = closed_by_symbol[agent["asset"]]
                signal_bar = closed[-1]
                signal_ts = _dt(signal_bar.ts) + timedelta(hours=1)
                signal_key = f"{agent['agent_id']}:{signal_bar.ts}:LONG"
                live = live_by_symbol[agent["asset"]]

                account = _account(cur)
                positions = _open_positions(cur)
                marks = _mark_equity(account, positions, live_by_symbol, config)

                atr = _atr_at(closed, len(closed) - 1)
                raw_entry = live.close
                entry = _fill_price(raw_entry, "BUY", config.slippage_bps_per_side)
                stop_distance = max(atr * config.atr_stop_multiple, entry * 0.0025)
                stop = max(0.0, entry - stop_distance)
                target = entry + stop_distance * config.reward_to_risk
                qty, risk_budget, notional = _position_size(
                    marks["equity"], entry, stop, config
                )
                cur.execute(
                    "SELECT role,risk_multiplier FROM aegis.agent_allocations WHERE agent_id=%s",
                    (agent["agent_id"],),
                )
                allocation = cur.fetchone()
                multiplier = min(1.0, max(0.0, _num(allocation["risk_multiplier"]))) if allocation else (1.0 if agent["status"] == "ACTIVE" else 0.0)
                qty *= multiplier
                risk_budget *= multiplier
                notional *= multiplier

                decision = "ALLOW"
                reason = None
                if (agent["agent_id"], agent["asset"]) in open_keys:
                    decision, reason = "DUPLICATE_POSITION", "Agent already has an open position."
                elif agent["status"] != "ACTIVE":
                    decision, reason = "SHADOW", f"Agent status {agent['status']}: shadow-only signal."
                elif allocation and allocation["role"] != "ACTIVE_PAPER":
                    decision, reason = "BLOCKED_EVOLUTION", f"Allocation gate: {allocation['role']}."
                elif circuit != "OPEN":
                    decision, reason = "BLOCKED_RISK", f"Portfolio circuit state {circuit}."
                elif len(positions) >= MAX_CONCURRENT_POSITIONS:
                    decision, reason = "BLOCKED_RISK", "Portfolio concurrent-position cap reached."
                elif not math.isfinite(qty) or qty <= 0:
                    decision, reason = "BLOCKED_RISK", "Risk engine produced zero position size."
                elif marks["total_notional"] + notional > marks["equity"] * MAX_TOTAL_NOTIONAL_PCT:
                    decision, reason = "BLOCKED_RISK", "Portfolio notional cap reached."

                cur.execute(
                    "INSERT INTO aegis.signals"
                    "(signal_key,agent_id,symbol,candle_ts,side,signal_price,decision,reason,snapshot) "
                    "VALUES (%s,%s,%s,%s,'LONG',%s,%s,%s,%s::jsonb) "
                    "ON CONFLICT (signal_key) DO NOTHING",
                    (
                        signal_key,
                        agent["agent_id"],
                        agent["asset"],
                        signal_ts,
                        signal_bar.close,
                        decision,
                        reason,
                        json.dumps(
                            {
                                "survival_score": agent["survival_score"],
                                "status": agent["status"],
                                "observed_live_price": live.close,
                            }
                        ),
                    ),
                )

                if decision != "ALLOW":
                    if decision != "DUPLICATE_POSITION":
                        ghost_id = _id("ghost", signal_key)
                        cur.execute(
                            "INSERT INTO aegis.ghost_trades"
                            "(ghost_id,signal_key,agent_id,symbol,side,signal_ts,signal_price,reason,"
                            "settlement_due_at,outcome) "
                            "VALUES (%s,%s,%s,%s,'LONG',%s,%s,%s,%s,%s::jsonb) "
                            "ON CONFLICT (signal_key) DO NOTHING",
                            (
                                ghost_id,
                                signal_key,
                                agent["agent_id"],
                                agent["asset"],
                                signal_ts,
                                raw_entry,
                                reason,
                                signal_ts + timedelta(hours=12),
                                json.dumps(
                                    {
                                        "survival_score": agent["survival_score"],
                                        "decision": decision,
                                    }
                                ),
                            ),
                        )
                        summary["ghosts"] += 1
                    continue

                order_id = _id("ord", signal_key)
                cur.execute(
                    "INSERT INTO aegis.paper_orders"
                    "(order_id,account_id,signal_key,agent_id,symbol,side,order_type,qty,"
                    "requested_price,stop_price,target_price,status,submitted_at,filled_at,metadata) "
                    "VALUES (%s,%s,%s,%s,%s,'BUY','MARKET',%s,%s,%s,%s,'FILLED',%s,%s,%s::jsonb) "
                    "ON CONFLICT (signal_key) DO NOTHING RETURNING order_id",
                    (
                        order_id,
                        ACCOUNT_ID,
                        signal_key,
                        agent["agent_id"],
                        agent["asset"],
                        qty,
                        raw_entry,
                        stop,
                        target,
                        scheduled_at,
                        scheduled_at,
                        json.dumps(
                            {
                                "risk_budget": risk_budget,
                                "signal_reason": _signal_reason(agent["strategy"]),
                            }
                        ),
                    ),
                )
                if cur.fetchone() is None:
                    continue

                entry_fee = _fee(entry * qty, config.fee_bps_per_side)
                entry_slippage = max(0.0, entry - raw_entry) * qty
                cur.execute(
                    "INSERT INTO aegis.paper_fills"
                    "(fill_id,order_id,fill_kind,fill_ts,fill_price,qty,fee,slippage_cost,metadata) "
                    "VALUES (%s,%s,'ENTRY',%s,%s,%s,%s,%s,%s::jsonb) "
                    "ON CONFLICT (fill_id) DO NOTHING",
                    (
                        _id("fille", order_id),
                        order_id,
                        scheduled_at,
                        entry,
                        qty,
                        entry_fee,
                        entry_slippage,
                        json.dumps({"source": "NEON_HOURLY_FORWARD"}),
                    ),
                )
                cur.execute(
                    "INSERT INTO aegis.paper_positions"
                    "(position_id,account_id,agent_id,symbol,side,qty,entry_price,stop_price,target_price,"
                    "opened_at,status,last_mark_price,unrealized_pnl) "
                    "VALUES (%s,%s,%s,%s,'LONG',%s,%s,%s,%s,%s,'OPEN',%s,0) "
                    "ON CONFLICT (position_id) DO NOTHING",
                    (
                        order_id,
                        ACCOUNT_ID,
                        agent["agent_id"],
                        agent["asset"],
                        qty,
                        entry,
                        stop,
                        target,
                        scheduled_at,
                        live.close,
                    ),
                )
                cur.execute(
                    "UPDATE aegis.paper_accounts SET cash=cash-%s,updated_at=now() WHERE account_id=%s",
                    (entry_fee, ACCOUNT_ID),
                )
                cur.execute(
                    "INSERT INTO aegis.audit_events"
                    "(event_key,entity_type,entity_id,event_type,occurred_at,payload) "
                    "VALUES (%s,'position',%s,'POSITION_OPENED',%s,%s::jsonb) "
                    "ON CONFLICT (event_key) DO NOTHING",
                    (
                        f"open:{order_id}",
                        order_id,
                        scheduled_at,
                        json.dumps(
                            {
                                "agent_id": agent["agent_id"],
                                "symbol": agent["asset"],
                                "qty": qty,
                                "entry": entry,
                                "stop": stop,
                                "target": target,
                            }
                        ),
                    ),
                )
                open_keys.add((agent["agent_id"], agent["asset"]))
                summary["entries"] += 1

            cur.execute(
                "SELECT * FROM aegis.ghost_trades "
                "WHERE settled_at IS NULL AND settlement_due_at <= %s "
                "ORDER BY settlement_due_at LIMIT 100",
                (scheduled_at,),
            )
            for ghost in cur.fetchall():
                candles = closed_by_symbol.get(ghost["symbol"], [])
                due = ghost["settlement_due_at"].astimezone(timezone.utc)
                bar = next((_bar for _bar in candles if _dt(_bar.ts) >= due), None)
                if not bar:
                    continue
                forward_return = bar.close / _num(ghost["signal_price"]) - 1.0
                cur.execute(
                    "UPDATE aegis.ghost_trades "
                    "SET settled_at=%s,forward_return=%s,outcome=outcome || %s::jsonb "
                    "WHERE ghost_id=%s AND settled_at IS NULL",
                    (
                        _dt(bar.ts) + timedelta(hours=1),
                        forward_return,
                        json.dumps({"settle_price": bar.close, "horizon": "12h"}),
                        ghost["ghost_id"],
                    ),
                )
                summary["settled_ghosts"] += 1

            account = _account(cur)
            positions = _open_positions(cur)
            unrealized = 0.0
            for p in positions:
                mark = live_by_symbol[p["symbol"]].close
                qty = _num(p["qty"])
                u = (
                    (mark - _num(p["entry_price"])) * qty
                    - _fee(mark * qty, config.fee_bps_per_side)
                )
                unrealized += u
                cur.execute(
                    "UPDATE aegis.paper_positions "
                    "SET last_mark_price=%s,unrealized_pnl=%s,updated_at=now() "
                    "WHERE position_id=%s",
                    (mark, u, p["position_id"]),
                )

            account = _account(cur)
            equity = _num(account["cash"]) + unrealized
            peak = max(_num(account["peak_equity"]), equity)
            drawdown = 1.0 - equity / peak if peak > 0 else 0.0

            cur.execute(
                "UPDATE aegis.paper_accounts SET peak_equity=%s,updated_at=now() WHERE account_id=%s",
                (peak, ACCOUNT_ID),
            )
            cur.execute(
                "INSERT INTO aegis.equity_curve"
                "(account_id,ts,cash,realized_pnl,unrealized_pnl,equity,peak_equity,drawdown,source_run_id) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (account_id,ts,source_run_id) DO NOTHING",
                (
                    ACCOUNT_ID,
                    scheduled_at,
                    _num(account["cash"]),
                    _num(account["realized_pnl"]),
                    unrealized,
                    equity,
                    peak,
                    drawdown,
                    run_id,
                ),
            )

            summary.update(
                {
                    "equity": equity,
                    "cash": _num(account["cash"]),
                    "realized_pnl": _num(account["realized_pnl"]),
                    "unrealized_pnl": unrealized,
                    "drawdown": drawdown,
                    "open_positions": len(positions),
                    "active_agents": sum(1 for a in agents if a["status"] == "ACTIVE"),
                    "circuit_state": circuit,
                }
            )
            # New gold agents join the INDEPENDENT shadow lab only. They are
            # intentionally excluded from the paper-main order-entry loop.
            shadow_agents = agents + gold_research_agents
            shadow_closed = dict(closed_by_symbol)
            shadow_live = dict(live_by_symbol)
            shadow_configs = {}
            if gold_research_agents:
                from dataclasses import replace
                from .gold_lab import (
                    GOLD_FEE_BPS_PER_SIDE, GOLD_SLIPPAGE_BPS_PER_SIDE,
                    record_gold_agents,
                )
                record_gold_agents(cur, gold_research_agents, run_id, scheduled_at)
                shadow_closed["XAU"] = gold_closed
                shadow_live["XAU"] = gold_live
                shadow_configs["XAU"] = replace(
                    config, fee_bps_per_side=GOLD_FEE_BPS_PER_SIDE,
                    slippage_bps_per_side=GOLD_SLIPPAGE_BPS_PER_SIDE,
                )
            summary["gold_research_status"] = gold_status
            summary["gold_feed_reason"] = gold_reason
            summary["gold_closed_bars"] = len(gold_closed) if gold_closed else 0
            summary["gold_agents_evaluated"] = len(gold_research_agents)
            summary["gold_live_execution"] = False
            # Independent costed shadow broker. All virtual fills and Stage 3
            # evidence share one atomic transaction with the paper account.
            # A repeated hourly run cannot duplicate fills.
            from .shadow_broker import run_shadow_tick
            shadow = run_shadow_tick(
                cur, run_id=run_id, now=scheduled_at, agents=shadow_agents,
                closed_by_symbol=shadow_closed,
                live_by_symbol=shadow_live, config=config,
                config_by_symbol=shadow_configs,
            )
            summary.update(shadow)

            # Evolution is reviewed AFTER costed shadow fills are persisted.
            # The deterministic portfolio risk constitution remains authoritative.
            from .stage3 import review_run
            review_run(cur, run_id, scheduled_at, shadow_agents, account, summary)
            cur.execute(
                "UPDATE aegis.engine_runs "
                "SET completed_at=now(),status='COMPLETED',summary=%s::jsonb WHERE run_id=%s",
                (json.dumps(summary), run_id),
            )

        conn.commit()

    return {"ok": True, "run_id": run_id, "scheduled_at": scheduled_at.isoformat(), **summary}


def get_forward_state() -> dict:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM aegis.paper_accounts WHERE account_id=%s", (ACCOUNT_ID,))
            account = cur.fetchone()
            if not account:
                return {
                    "ok": True,
                    "initialized": False,
                    "mode": "FORWARD_PAPER",
                    "message": "Persistent broker has not run yet.",
                }

            cur.execute(
                "SELECT * FROM aegis.paper_positions WHERE account_id=%s AND status='OPEN' ORDER BY opened_at",
                (ACCOUNT_ID,),
            )
            positions = list(cur.fetchall())
            cur.execute(
                "SELECT * FROM aegis.paper_trades WHERE account_id=%s ORDER BY exit_ts DESC LIMIT 50",
                (ACCOUNT_ID,),
            )
            trades = list(cur.fetchall())
            cur.execute(
                "SELECT count(*) AS closed_trades, "
                "count(*) FILTER (WHERE net_pnl > 0) AS wins, "
                "COALESCE(sum(net_pnl) FILTER (WHERE net_pnl > 0),0) AS gains, "
                "COALESCE(abs(sum(net_pnl) FILTER (WHERE net_pnl < 0)),0) AS losses "
                "FROM aegis.paper_trades WHERE account_id=%s",
                (ACCOUNT_ID,),
            )
            trade_stats = cur.fetchone()
            cur.execute(
                "SELECT ts,cash,realized_pnl,unrealized_pnl,equity,peak_equity,drawdown "
                "FROM aegis.equity_curve WHERE account_id=%s ORDER BY ts DESC LIMIT 200",
                (ACCOUNT_ID,),
            )
            equity_curve = list(cur.fetchall())
            cur.execute(
                "SELECT run_id,started_at,completed_at,status,summary FROM aegis.engine_runs "
                "WHERE mode='FORWARD_PAPER' ORDER BY started_at DESC LIMIT 20"
            )
            runs = list(cur.fetchall())
            cur.execute(
                "SELECT agent_id,asset,strategy,status,survival_score,evidence,updated_at "
                "FROM aegis.agent_registry ORDER BY survival_score DESC"
            )
            agents = list(cur.fetchall())

    gains = _num(trade_stats["gains"])
    losses = _num(trade_stats["losses"])
    wins = int(trade_stats["wins"] or 0)
    closed_trades = int(trade_stats["closed_trades"] or 0)
    pf = gains / losses if losses > 0 else (99.0 if gains > 0 else 0.0)
    latest_equity = _num(equity_curve[0]["equity"]) if equity_curve else _num(account["cash"])

    return _json_safe(
        {
            "ok": True,
            "initialized": True,
            "mode": "FORWARD_PAPER",
            "live_execution_enabled": False,
            "account": account,
            "vault": {
                "marked_equity": latest_equity,
                "realized_pnl": _num(account["realized_pnl"]),
                "open_positions": len(positions),
                "closed_trades": closed_trades,
                "win_rate": wins / closed_trades if closed_trades else 0.0,
                "profit_factor": pf,
                "circuit_state": account["circuit_state"],
            },
            "positions": positions,
            "trades": trades,
            "equity_curve": list(reversed(equity_curve)),
            "runs": runs,
            "agents": agents,
        }
    )
