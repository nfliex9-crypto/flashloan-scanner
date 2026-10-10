"""No 1-minute Paper entries. BTC 1m remains a verified quote source only."""
from contextlib import contextmanager
from datetime import datetime, timezone

from aegis.live_lab import Candle
from aegis.stream_core import ALLOWED_MINUTES, TRADING_MINUTES, QUOTE_ONLY_MINUTES, CompletedBar
from aegis.stream_paper import persist_closed_stream_bar, fill_decision, RISK


NOW=datetime(2026,10,10,10,15,tzinfo=timezone.utc)
BAR=int(NOW.timestamp())//60*60-60


def bar_event():
    c=Candle(ts=BAR,open=80000.,high=80010.,low=79990.,close=80001.,volume=1.)
    return CompletedBar("BTC",1,c,80005.,BAR+60)


class Cursor:
    def __init__(self,old_position=False):
        self.commands=[]
        self.last=""
        self.old_position=old_position
        self.trades=0
    def execute(self,sql,args=()):
        self.last=sql
        self.commands.append((sql,args))
    def fetchone(self):
        s=self.last
        if "stream_bar_ledger" in s and "RETURNING" in s:
            return {"bar_start":NOW}
        if "SELECT 1 FROM aegis.stream_positions" in s:
            return {"?column?":1} if self.old_position else None
        if "FROM aegis.stream_accounts WHERE agent_id" in s:
            if "ema-cross" not in self.commands[-1][1][0]:return None
            return {"agent_id":"micro-btc-1m-ema-cross","strategy":"EMA Cross",
                    "direction":"LONG","cash":100000.0,
                    "peak_equity":100000.0,"max_drawdown":0.,"halted":False}
        if "FROM aegis.stream_positions WHERE agent_id" in s:
            if "ema-cross" not in self.commands[-1][1][0]:return None
            return {"agent_id":"micro-btc-1m-ema-cross",
                    "position_id":"legacy-paper-1m","direction":"LONG",
                    "symbol":"BTC","opened_at":NOW.replace(minute=0),
                    "entry_price":79990.,"entry_fee":2.4,"entry_slippage":1.,
                    "qty":.1,"stop_price":79000.,"target_price":81000.}
        if "INSERT INTO aegis.stream_trades" in s:
            self.trades+=1
            return {"position_id":"legacy-paper-1m"}
        raise AssertionError("Unexpected fetchone: "+s)


class Connection:
    def __init__(self,cursor):self.cur=cursor
    @contextmanager
    def transaction(self):
        yield self
    @contextmanager
    def cursor(self):
        yield self.cur


def test_one_minute_feed_is_allowed_but_trading_is_disabled():
    assert 1 in ALLOWED_MINUTES
    assert QUOTE_ONLY_MINUTES == (1,)
    assert 1 not in TRADING_MINUTES
    assert TRADING_MINUTES == (5,15,60,240,1440,10080)


def test_one_minute_signal_function_cannot_open_position():
    account={"strategy":"EMA Cross","direction":"LONG","halted":False,
             "cash":100000.,"max_drawdown":0.}
    decision=fill_decision(account,None,[],bar_event(),config=RISK)
    assert decision=={"action":"WAIT","reason":"TIMEFRAME_QUOTE_ONLY_1M"}


def test_verified_one_minute_bar_is_persisted_without_any_bot_or_decision():
    cur=Cursor()
    result=persist_closed_stream_bar(Connection(cur),bar_event(),[])
    assert result["processed"] is True
    assert result["entries"]==0 and result["exits"]==0
    sql="\n".join(q for q,_ in cur.commands)
    assert "INSERT INTO aegis.stream_candles" in sql
    assert "INSERT INTO aegis.stream_bar_ledger" in sql
    assert "INSERT INTO aegis.stream_accounts" not in sql
    assert "INSERT INTO aegis.stream_decisions" not in sql
    assert "INSERT INTO aegis.stream_positions" not in sql
    assert "INSERT INTO aegis.stream_trades" not in sql


def test_existing_one_minute_virtual_position_is_retired_once_with_costs():
    cur=Cursor(old_position=True)
    result=persist_closed_stream_bar(Connection(cur),bar_event(),[])
    assert result["processed"] is True
    assert result["entries"]==0
    assert result["exits"]==1
    sql="\n".join(q for q,_ in cur.commands)
    assert "INSERT INTO aegis.stream_accounts" not in sql
    assert "INSERT INTO aegis.stream_positions" not in sql
    assert "INSERT INTO aegis.stream_trades" in sql
    assert "DELETE FROM aegis.stream_positions" in sql
    assert any("TIMEFRAME_1M_RETIRED" in repr(params) for _,params in cur.commands)


def test_five_minute_bots_continue_to_be_trade_eligible():
    from aegis.bot_fleet import project_paper_bots
    acc=[{"agent_id":"retired1m","symbol":"BTC","interval_minutes":1,
          "strategy":"EMA Cross","direction":"LONG","cash":100000.},
         {"agent_id":"enabled5m","symbol":"BTC","interval_minutes":5,
          "strategy":"EMA Cross","direction":"SHORT","cash":100000.}]
    result=project_paper_bots(acc,[],[],[1,5],[])
    assert [b["bot_id"] for b in result]==["enabled5m"]
    assert result[0]["feed_verified"] is True
