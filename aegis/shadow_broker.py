"""Forward-only costed shadow execution for all AEGIS research agents.

This is an isolated virtual portfolio per agent. It is NEVER funded, never
writes paper_orders, and cannot place real orders. Entry signals use the
latest *closed* hourly candle; model fills use the current observed quote
at the scheduled run, not hypothetical past next-open fills.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta, timezone

from .live_lab import strategy_positions
from .paper_engine import RiskConfig, _atr_at, _fee, _fill_price, _position_size

SHADOW_STARTING_EQUITY = 100_000.0


def shadow_id(kind: str, *parts: object) -> str:
    digest = hashlib.sha256("|".join(map(str,parts)).encode("utf8")).hexdigest()[:24]
    return f"shadow-{kind}-{digest}"


def shadow_entry_price(raw: float, config: RiskConfig) -> float:
    return _fill_price(raw, "BUY", config.slippage_bps_per_side)


def shadow_exit_result(
    position: dict, raw_exit: float, config: RiskConfig
) -> dict:
    """Pure costed long exit, independent of database state."""
    if raw_exit <= 0 or not math.isfinite(raw_exit):
        raise ValueError("Invalid shadow exit price")
    price = _fill_price(raw_exit, "SELL", config.slippage_bps_per_side)
    qty = float(position["qty"])
    entry = float(position["entry_price"])
    entry_fee = float(position["entry_fee"])
    slippage_in = float(position["entry_slippage"])
    gross = (price - entry) * qty
    exit_fee = _fee(price * qty, config.fee_bps_per_side)
    exit_slippage = max(0.0, raw_exit - price) * qty
    net = gross - entry_fee - exit_fee
    risk = max((entry - float(position["stop_price"])) * qty, 1e-9)
    return {
        "exit_price": price,
        "gross": gross,
        "entry_fee": entry_fee,
        "exit_fee": exit_fee,
        "slippage_cost": slippage_in + exit_slippage,
        "net_pnl": net,
        "r_multiple": net / risk,
    }


def shadow_bar_exit(position: dict, candles: list) -> tuple[float,str,datetime] | None:
    """Conservative OHLC stops: omit pre-entry data, assume stop if both touched."""
    opened_at = position["opened_at"]
    for candle in candles:
        start = datetime.fromtimestamp(candle.ts,tz=timezone.utc)
        if start < opened_at:
            continue
        stop = float(position["stop_price"])
        target = float(position["target_price"])
        stop_hit = candle.low <= stop
        target_hit = candle.high >= target
        end = start + timedelta(hours=1)
        if stop_hit and target_hit:
            return stop,"STOP_AMBIGUOUS_BAR",end
        if stop_hit:
            return stop,"STOP",end
        if target_hit:
            return target,"TARGET",end
    return None


def run_shadow_tick(
    cur, *, run_id: str, now: datetime, agents: list[dict],
    closed_by_symbol: dict, live_by_symbol: dict, config: RiskConfig
) -> dict:
    """Call exactly once inside the forward broker's existing transaction."""
    from .stage3 import emit_event

    stats = {"shadow_entries":0,"shadow_exits":0,"shadow_open":0}
    by_id = {a["agent_id"]:a for a in agents}

    for agent in agents:
        agent_id = agent["agent_id"]
        cur.execute(
            "INSERT INTO aegis.shadow_accounts(agent_id,starting_equity,cash,peak_equity,initialized_at,updated_at) "
            "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(agent_id) DO NOTHING",
            (agent_id, SHADOW_STARTING_EQUITY, SHADOW_STARTING_EQUITY,
             SHADOW_STARTING_EQUITY,now,now),
        )

    # Step 1: resolve each open virtual position using only bars that have
    # fully closed since entry. No pre-entry high/low is accessed.
    cur.execute("SELECT * FROM aegis.shadow_positions ORDER BY agent_id")
    positions = list(cur.fetchall())
    for p in positions:
        asset = p["symbol"]
        if asset not in closed_by_symbol or asset not in live_by_symbol:
            continue
        close = shadow_bar_exit(p, closed_by_symbol[asset])
        agent = by_id.get(p["agent_id"])
        if close is None and agent and agent["latest_signal"] == "FLAT":
            close = (live_by_symbol[asset].close, "SIGNAL_EXIT", now)
        if close is None:
            continue

        raw_exit, reason, exit_ts = close
        result = shadow_exit_result(p, raw_exit, config)
        tid = shadow_id("trade",p["position_id"])
        cur.execute(
            "INSERT INTO aegis.shadow_trades "
            "(trade_id,position_id,agent_id,signal_key,symbol,opened_at,closed_at,"
            "raw_entry,entry_price,exit_price,qty,gross_pnl,entry_fee,exit_fee,"
            "slippage_cost,net_pnl,r_multiple,reason,evidence) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb) "
            "ON CONFLICT(position_id) DO NOTHING RETURNING trade_id",
            (tid,p["position_id"],p["agent_id"],p["signal_key"],asset,p["opened_at"],
             exit_ts,p["raw_entry"],p["entry_price"],result["exit_price"],p["qty"],
             result["gross"],result["entry_fee"],result["exit_fee"],result["slippage_cost"],
             result["net_pnl"],result["r_multiple"],reason,
             json.dumps({"run_id":run_id,"fee_bps_each_side":config.fee_bps_per_side,
                         "slippage_bps_each_side":config.slippage_bps_per_side,
                         "source":"FORWARD_COSTED_SHADOW","live_execution":False})),
        )
        if cur.fetchone() is None:
            continue
        cur.execute("DELETE FROM aegis.shadow_positions WHERE position_id=%s",(p["position_id"],))
        # Entry commission already deducted at time of virtual opening.
        cash_change = result["gross"] - result["exit_fee"]
        cur.execute(
            "UPDATE aegis.shadow_accounts SET cash=cash+%s,realized_pnl=realized_pnl+%s,"
            "updated_at=%s WHERE agent_id=%s",
            (cash_change,result["net_pnl"],now,p["agent_id"]),
        )
        emit_event(cur,key=f"shadow-exit:{tid}",kind="SHADOW_EXIT",scope="SHADOW",
                   title=f"{asset} costed shadow trade closed",agent=p["agent_id"],
                   symbol=asset,amount=result["net_pnl"],run_id=run_id,at=now,
                   severity="success" if result["net_pnl"]>=0 else "danger",
                   description=f"{reason} · independent virtual account, after fees/slippage")
        stats["shadow_exits"]+=1

    # Step 2: new CLOSED-bar transitions. Every worker is modelled, even
    # a research-approved paper incumbent, to make costed comparisons possible.
    for agent in agents:
        symbol = agent["asset"]
        aid = agent["agent_id"]
        candles = closed_by_symbol.get(symbol,[])
        if len(candles)<30 or symbol not in live_by_symbol:
            continue
        closes = [c.close for c in candles]
        positions = strategy_positions(closes,agent["strategy"],agent["generation"])
        if len(positions)<2 or not (positions[-1]==1 and positions[-2]==0):
            continue
        signal_key = f"shadow:{aid}:{candles[-1].ts}:LONG"
        cur.execute("SELECT position_id FROM aegis.shadow_positions WHERE agent_id=%s",(aid,))
        if cur.fetchone():
            continue
        cur.execute("SELECT trade_id FROM aegis.shadow_trades WHERE signal_key=%s",(signal_key,))
        if cur.fetchone():
            continue
        cur.execute("SELECT * FROM aegis.shadow_accounts WHERE agent_id=%s FOR UPDATE",(aid,))
        account = cur.fetchone()
        if not account:
            continue
        mark = live_by_symbol[symbol].close
        if mark<=0 or not math.isfinite(mark):
            continue
        entry = shadow_entry_price(mark,config)
        atr = _atr_at(candles,len(candles)-1)
        stop_distance = max(atr*config.atr_stop_multiple,entry*0.0025)
        stop = max(0.0,entry-stop_distance)
        target = entry+stop_distance*config.reward_to_risk
        virtual_equity = float(account["cash"])
        qty, _, notional = _position_size(virtual_equity,entry,stop,config)
        if qty<=0 or not math.isfinite(qty):
            continue
        entry_fee = _fee(entry*qty,config.fee_bps_per_side)
        slip_cost = max(0,entry-mark)*qty
        pos_id = shadow_id("position",signal_key)
        cur.execute(
            "INSERT INTO aegis.shadow_positions "
            "(agent_id,position_id,signal_key,symbol,opened_at,raw_entry,entry_price,qty,"
            "stop_price,target_price,entry_fee,entry_slippage,last_mark,unrealized_pnl,updated_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT(agent_id) DO NOTHING RETURNING position_id",
            (aid,pos_id,signal_key,symbol,now,mark,entry,qty,stop,target,
             entry_fee,slip_cost,mark,-entry_fee,now),
        )
        if cur.fetchone() is None:
            continue
        cur.execute("UPDATE aegis.shadow_accounts SET cash=cash-%s,updated_at=%s WHERE agent_id=%s",
                    (entry_fee,now,aid))
        emit_event(cur,key=f"shadow-entry:{pos_id}",kind="SHADOW_ENTRY",
                   scope="SHADOW",title=f"{symbol} costed shadow LONG opened",
                   agent=aid,symbol=symbol,run_id=run_id,at=now,
                   description="Virtual fill observed at hourly tick; fees and slippage modelled")
        stats["shadow_entries"]+=1

    # Step 3: mark-to-market each independent account, peak and intra-trade DD.
    cur.execute("SELECT * FROM aegis.shadow_positions")
    open_positions=list(cur.fetchall())
    positions_by_agent={p["agent_id"]:p for p in open_positions}
    for agent in agents:
        aid=agent["agent_id"]
        p=positions_by_agent.get(aid)
        u=0.0
        if p:
            mark=live_by_symbol[p["symbol"]].close
            qty=float(p["qty"])
            u=(mark-float(p["entry_price"]))*qty-_fee(mark*qty,config.fee_bps_per_side)
            cur.execute(
                "UPDATE aegis.shadow_positions SET last_mark=%s,unrealized_pnl=%s,updated_at=%s "
                "WHERE agent_id=%s",(mark,u,now,aid))
        cur.execute("SELECT cash,peak_equity,max_drawdown FROM aegis.shadow_accounts WHERE agent_id=%s",(aid,))
        a=cur.fetchone()
        equity=float(a["cash"])+u
        peak=max(float(a["peak_equity"]),equity)
        dd=max(float(a["max_drawdown"]),1.0-equity/peak) if peak>0 else 0.0
        cur.execute(
            "UPDATE aegis.shadow_accounts SET peak_equity=%s,max_drawdown=%s,updated_at=%s WHERE agent_id=%s",
            (peak,dd,now,aid),
        )
    stats["shadow_open"]=len(open_positions)
    return stats
