"""Independent, costed, paper-only execution ledger for public Kraken OHLC.

The only side effects are SQL inserts/updates in aegis.stream_* tables.
No HTTP broker, credentials, wallet, leveraged execution or main paper account.
Every closed bar is idempotent, with all fills atomic in one Neon transaction.
"""
from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone

from .live_lab import Candle
from .directional_signals import signed_strategy_signals
from .paper_engine import RiskConfig, _atr_at, _fee, _fill_price, _position_size
from .shadow_broker import conservative_stop_fill
from .stream_core import CompletedBar, fresh_closed_history

STRATEGIES = ("EMA Cross", "Channel Breakout")
STARTING_EQUITY = 100000.0
MICRO_DIRECTIONS = ("LONG","SHORT")
SHORT_FINANCE_BPS_PER_DAY = 2.0
RISK = RiskConfig(risk_per_trade=.0025,max_position_notional_pct=.20,
                  max_agent_drawdown_pct=.05,
                  fee_bps_per_side=3.0,slippage_bps_per_side=2.0)


def utc(ts: int) -> datetime:
    return datetime.fromtimestamp(ts,timezone.utc)


def stream_agent_id(symbol: str, minutes: int, strategy: str,
                    direction: str = "LONG") -> str:
    if direction not in MICRO_DIRECTIONS:
        raise ValueError("Only independent LONG/SHORT micro research cohorts supported")
    name=strategy.lower().replace(" ","-")
    suffix="" if direction=="LONG" else "-short"
    return f"micro-{symbol.lower()}-{minutes}m-{name}{suffix}"


def _model_short_financing(pos:dict,at:int)->float:
    if pos.get("direction","LONG")!="SHORT":
        return 0.0
    opened=pos["opened_at"]
    secs=max(0.0,at-opened.timestamp())
    return (float(pos["entry_price"])*float(pos["qty"])*
            SHORT_FINANCE_BPS_PER_DAY/10000*secs/86400)


def fill_decision(account: dict, position: dict | None, history: list[Candle],
                  event: CompletedBar, *, config: RiskConfig = RISK) -> dict:
    """One fully closed bar may yield a new next-open VIRTUAL fill only."""
    closed=event.candle
    now_open=event.next_open
    minutes=event.interval_minutes
    if not (math.isfinite(now_open) and now_open>0):
        raise ValueError("Invalid observed next candle open")
    strategy=account["strategy"]
    direction=account.get("direction","LONG")
    if direction not in MICRO_DIRECTIONS:
        raise ValueError("Unknown research cohort direction")
    side=1 if direction=="LONG" else -1
    pos=position
    if pos:
        if pos.get("direction","LONG")!=direction:
            raise ValueError("Direction mismatch in independent virtual account")
        opened=pos["opened_at"]
        if opened.tzinfo is None:
            raise ValueError("Position time must be UTC-aware")
        if closed.ts+60*minutes>opened.timestamp():
            stop=float(pos["stop_price"]);target=float(pos["target_price"])
            stop_hit=closed.low<=stop if side==1 else closed.high>=stop
            target_hit=closed.high>=target if side==1 else closed.low<=target
            if stop_hit:
                raw=(min(stop,closed.open) if side==1 else max(stop,closed.open))
                return {"action":"EXIT","raw_price":raw,
                        "reason":"STOP_AMBIGUOUS_BAR" if target_hit else "STOP",
                        "at":utc(closed.ts+minutes*60)}
            if target_hit:
                return {"action":"EXIT","raw_price":target,"reason":"TARGET",
                        "at":utc(closed.ts+minutes*60)}
    contiguous=fresh_closed_history(history,minutes)
    signal=previous=None
    if contiguous:
        values=signed_strategy_signals([c.close for c in history],strategy,direction)
        signal=values[-1];previous=values[-2]
    if pos:
        if signal!=side and previous==side:
            return {"action":"EXIT","raw_price":now_open,
                    "reason":"SIGNAL_EXIT","at":utc(event.next_start)}
        return {"action":"MARK","price":closed.close}
    if not contiguous or bool(account["halted"]) or float(account["max_drawdown"])>=.05:
        return {"action":"WAIT","reason":"HALTED_OR_INSUFFICIENT_CLOSED_HISTORY"}
    if signal!=side or previous==side:
        return {"action":"WAIT","reason":"NO_FRESH_CLOSED_BAR_ENTRY"}
    entry=_fill_price(now_open,"BUY" if side==1 else "SELL",
                      config.slippage_bps_per_side)
    atr=_atr_at(history,len(history)-1)
    stop_distance=max(atr*config.atr_stop_multiple,entry*.0025)
    stop=entry-side*stop_distance
    target=entry+side*stop_distance*config.reward_to_risk
    risk_budget=max(0.0,float(account["cash"])*config.risk_per_trade)
    cap=max(0.0,float(account["cash"])*config.max_position_notional_pct)
    qty=min(risk_budget/abs(stop-entry),cap/entry)
    if not (math.isfinite(qty) and qty>0 and stop>0 and target>0 and
            qty*entry<=cap+1e-6):
        return {"action":"WAIT","reason":"RISK_SIZE_VETO"}
    notional=entry*qty
    return {"action":"ENTER","direction":direction,
            "entry":entry,"stop":stop,"target":target,
            "qty":qty,"notional":notional,
            "entry_fee":_fee(notional,config.fee_bps_per_side),
            "entry_slippage":abs(entry-now_open)*qty,
            "at":utc(event.next_start)}


def _update_account_risk(cur, aid: str, account: dict, position: dict | None,
                         price: float, config: RiskConfig,
                         *, mark_at: int) -> None:
    equity=float(account["cash"])
    if position:
        side=1 if position.get("direction","LONG")=="LONG" else -1
        qty=float(position["qty"])
        entry=float(position["entry_price"])
        equity+=(side*(price-entry)*qty
                 -_fee(price*qty,config.fee_bps_per_side)
                 -_model_short_financing(position,mark_at))
    peak=max(float(account["peak_equity"]),equity)
    dd=max(float(account["max_drawdown"]),1-equity/peak if peak>0 else 0.)
    cur.execute(
        "UPDATE aegis.stream_accounts SET peak_equity=%s,max_drawdown=%s,"
        "halted=(halted OR %s),updated_at=now() WHERE agent_id=%s",
        (peak,dd,dd>=config.max_agent_drawdown_pct,aid))


def persist_closed_stream_bar(conn, event: CompletedBar, history: list[Candle],
                              *, config: RiskConfig=RISK) -> dict:
    """Idempotent virtual decisions across restarts/replicas.

    The claimed bar and all virtual state changes commit or roll back as ONE.
    The caller never sends an exchange request.
    """
    c=event.candle
    symbol=event.symbol
    minutes=event.interval_minutes
    counts={"processed":False,"entries":0,"exits":0,"marks":0,"filtered":0}
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO aegis.stream_bar_ledger(symbol,interval_minutes,bar_start) "
                "VALUES(%s,%s,%s) ON CONFLICT DO NOTHING RETURNING bar_start",
                (symbol,minutes,utc(c.ts)))
            if cur.fetchone() is None:
                return counts
            cur.execute(
                "INSERT INTO aegis.stream_candles "
                "(symbol,interval_minutes,bar_start,open,high,low,close,volume) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (symbol,minutes,utc(c.ts),c.open,c.high,c.low,c.close,c.volume))
            counts["processed"]=True
            for strategy in STRATEGIES:
              for direction in MICRO_DIRECTIONS:
                aid=stream_agent_id(symbol,minutes,strategy,direction)
                cur.execute(
                    "INSERT INTO aegis.stream_accounts(agent_id,symbol,interval_minutes,strategy,direction) "
                    "VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (aid,symbol,minutes,strategy,direction))
                cur.execute("SELECT * FROM aegis.stream_accounts WHERE agent_id=%s FOR UPDATE",(aid,))
                acc=cur.fetchone()
                cur.execute("SELECT * FROM aegis.stream_positions WHERE agent_id=%s FOR UPDATE",(aid,))
                pos=cur.fetchone()
                decision=fill_decision(acc,pos,history,event,config=config)
                action=decision["action"]
                if action=="EXIT" and pos:
                    raw=decision["raw_price"]
                    side=1 if direction=="LONG" else -1
                    exit_price=_fill_price(raw,"SELL" if side==1 else "BUY",
                                           config.slippage_bps_per_side)
                    qty=float(pos["qty"])
                    entry=float(pos["entry_price"])
                    entry_fee=float(pos["entry_fee"])
                    exit_fee=_fee(exit_price*qty,config.fee_bps_per_side)
                    financing=_model_short_financing(pos,int(decision["at"].timestamp()))
                    gross=side*(exit_price-entry)*qty
                    net=gross-entry_fee-exit_fee-financing
                    slip=float(pos["entry_slippage"])+abs(raw-exit_price)*qty
                    cur.execute(
                        "INSERT INTO aegis.stream_trades "
                        "(position_id,agent_id,symbol,interval_minutes,opened_at,closed_at,"
                        "entry_price,exit_price,qty,entry_fee,exit_fee,slippage_cost,net_pnl,reason,direction,financing_cost) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                        "ON CONFLICT DO NOTHING RETURNING position_id",
                        (pos["position_id"],aid,symbol,minutes,pos["opened_at"],decision["at"],
                         entry,exit_price,qty,entry_fee,exit_fee,slip,net,decision["reason"],
                         direction,financing))
                    if cur.fetchone() is None:
                        raise RuntimeError("Duplicate virtual exit without accounting confirmation")
                    cur.execute("DELETE FROM aegis.stream_positions WHERE agent_id=%s",(aid,))
                    cash=float(acc["cash"])+gross-exit_fee-financing
                    cur.execute("UPDATE aegis.stream_accounts SET cash=%s,updated_at=now() WHERE agent_id=%s",
                                (cash,aid))
                    acc={**acc,"cash":cash}
                    counts["exits"]+=1
                    pos=None
                elif action=="ENTER":
                    # Independent forward evidence gate; historical backtests
                    # alone NEVER promote micro strategies. Only settled costed
                    # virtual fills can quarantine an underperformer.
                    cur.execute(
                        "SELECT count(*) AS trades,COALESCE(sum(net_pnl),0) AS net,"
                        "COALESCE(sum(net_pnl) FILTER(WHERE net_pnl>0),0) AS gains,"
                        "COALESCE(abs(sum(net_pnl) FILTER(WHERE net_pnl<0)),0) AS losses "
                        "FROM aegis.stream_trades WHERE agent_id=%s",(aid,))
                    perf=cur.fetchone()
                    from .strategy_filter import evaluate_strategy
                    wins=int(perf["trades"])
                    gains=float(perf["gains"])
                    losses=float(perf["losses"])
                    pf=min(99.0,gains/losses) if losses>0 else (99.0 if gains>0 else 0.0)
                    rank=evaluate_strategy(trades=wins,wins=0,net=float(perf["net"]),
                                           profit_factor=pf,
                                           max_drawdown=float(acc["max_drawdown"]))
                    if rank["state"]=="QUARANTINED":
                        cur.execute("UPDATE aegis.stream_accounts SET halted=TRUE,updated_at=now() "
                                    "WHERE agent_id=%s",(aid,))
                        counts["filtered"]+=1
                        continue
                    # The deterministic signal can be logged after restart but
                    # never creates two positions for an agent.
                    position_id="stream-"+hashlib.sha256(
                        f"{aid}:{event.next_start}".encode()).hexdigest()[:24]
                    cur.execute(
                        "INSERT INTO aegis.stream_positions "
                        "(agent_id,position_id,symbol,interval_minutes,opened_at,"
                        "entry_price,qty,stop_price,target_price,entry_fee,entry_slippage,last_mark) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                        "ON CONFLICT DO NOTHING RETURNING position_id",
                        (aid,position_id,symbol,minutes,decision["at"],
                         decision["entry"],decision["qty"],decision["stop"],decision["target"],
                         decision["entry_fee"],decision["entry_slippage"],event.next_open,direction))
                    if cur.fetchone() is None:
                        raise RuntimeError("Duplicate virtual entry, rolled back")
                    cash=float(acc["cash"])-decision["entry_fee"]
                    cur.execute("UPDATE aegis.stream_accounts SET cash=%s,updated_at=now() WHERE agent_id=%s",
                                (cash,aid))
                    acc={**acc,"cash":cash}
                    pos={"entry_price":decision["entry"],"qty":decision["qty"],
                         "direction":direction,"opened_at":decision["at"]}
                    counts["entries"]+=1
                if action=="MARK" and pos:
                    cur.execute(
                        "UPDATE aegis.stream_positions SET last_mark=%s WHERE agent_id=%s",
                        (decision["price"],aid))
                    counts["marks"]+=1
                mark=event.next_open if action=="ENTER" else c.close
                _update_account_risk(cur,aid,acc,pos,mark,config,mark_at=event.next_start)
    return counts
