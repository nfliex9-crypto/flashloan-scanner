"""Actual API path tests for the lightweight BTC Paper desk (mocked Neon rows).

No synthetic price is written to production; test fixtures are never served.
"""
from datetime import datetime, timedelta, timezone
from api.stage3 import handler
from aegis import paper_desk

NOW=datetime(2026,10,10,8,30,20,tzinfo=timezone.utc)
BAR=NOW.replace(second=0,microsecond=0)-timedelta(minutes=1)


class ReadOnlyCursor:
    def __init__(self, *, missing=(), price=65000., bar_start=BAR,
                 open_positions=False, trade_count=0):
        self.missing=set(missing)
        self.price=price
        self.bar_start=bar_start
        self.open_positions=open_positions
        self.trade_count=trade_count
        self.last_sql=""
        self.last_params=None
        self.queries=[]

    def execute(self, sql, params=None):
        normalized=sql.upper()
        for prefix in ("UPDATE ","INSERT ","DELETE ","DROP ","ALTER ","CREATE ","TRUNCATE "):
            assert prefix not in normalized
        self.last_sql=sql
        self.last_params=params
        self.queries.append((sql,params))

    def fetchall(self):
        sql=self.last_sql
        if "to_regclass" in sql:
            return [{"name":name,"relation":None if name in self.missing else "aegis."+name}
                    for name in self.last_params[0]]
        if "stream_status WHERE" in sql:
            return [
                {"stream_name":f"kraken-public-micro-{i}m","state":"CONNECTED",
                 "last_message_at":NOW-timedelta(seconds=15),
                 "last_closed_bar":BAR,"updated_at":NOW-timedelta(seconds=15)}
                for i in (1,5,15)]
        if "FROM aegis.stream_accounts" in sql and "JOIN" not in sql:
            return [{"agent_id":"micro-btc-5m-ema-cross",
                    "symbol":"BTC","interval_minutes":5,"strategy":"EMA Cross",
                    "direction":"LONG","cash":99999,"peak_equity":100000.,
                    "max_drawdown":0.,"halted":False,"updated_at":NOW}]
        if "FROM aegis.stream_positions" in sql:
            if not self.open_positions:return []
            return [{"agent_id":"micro-btc-5m-ema-cross","position_id":"test-p1",
                    "symbol":"BTC","interval_minutes":5,"opened_at":NOW-timedelta(hours=1),
                    "entry_price":64000.,"qty":0.1,"stop_price":63000.,
                    "target_price":66000.,"last_mark":65000.,"direction":"LONG"}]
        if "FROM aegis.stream_trades t JOIN" in sql:
            if not self.trade_count:return []
            return [{"agent_id":"micro-btc-5m-ema-cross","strategy":"EMA Cross",
                    "symbol":"BTC","interval_minutes":5,"side":"LONG",
                    "trades":self.trade_count,"net_pnl":120.,
                    "gross_gains":200.,"gross_losses":-80.}]
        if "FROM aegis.stream_decisions" in sql:
            return [{"agent_id":"micro-btc-5m-ema-cross","bar_start":BAR,
                     "observed_at":NOW-timedelta(seconds=15),"symbol":"BTC",
                     "interval_minutes":5,"strategy":"EMA Cross","direction":"LONG",
                     "action":"WAIT","reason":"NO_FRESH_CLOSED_BAR_ENTRY",
                     "reference_price":65000.,"position_id":None,"qty":None,
                     "net_pnl":None}]
        if "FROM aegis.stream_trades" in sql:return []
        raise AssertionError("Unexpected SELECT: "+sql)

    def fetchone(self):
        if "FROM aegis.stream_candles" in self.last_sql:
            if self.bar_start is None:return None
            return {"bar_start":self.bar_start,"open":64990.,"high":65010.,
                    "low":64980.,"close":self.price,"volume":17.}
        raise AssertionError("Unexpected fetchone: "+self.last_sql)


def test_live_paper_desk_shows_source_candle_and_research_bots():
    cur=ReadOnlyCursor()
    doc=paper_desk.snapshot(cur,now=NOW)
    assert doc["ok"] is True and doc["initialized"] is True
    assert doc["market"]["price_kind"]=="PERSISTED_CLOSED_CANDLE"
    assert doc["market"]["close"]==65000.
    assert doc["market"]["live_tick"] is False
    assert doc["micro_engine"]["active_intervals_minutes"]==[1,5,15]
    bot=doc["micro_engine"]["paper_bots"][0]
    assert bot["closed_trades"]==0
    assert bot["net_pnl_after_costs"] is None
    assert bot["trade_order_permission"] is False
    assert len(doc["micro_engine"]["decision_journal"])==1
    assert len(cur.queries)>=7


def test_open_paper_pnl_is_signed_costed_and_never_a_real_position():
    doc=paper_desk.snapshot(ReadOnlyCursor(open_positions=True,trade_count=8),now=NOW)
    bot=doc["micro_engine"]["paper_bots"][0]
    expected=(65000-64000)*0.1-(65000*0.1)*0.0003
    assert bot["open_unrealized_net"]==round(expected,6)
    assert doc["pulse"]["paper_open_unrealized_net"]==round(expected,4)
    assert bot["net_pnl_after_costs"]==120.
    assert bot["closed_trades"]==8
    assert bot["oos_forward_qualified"] is False
    assert doc["live_execution_enabled"] is False
    assert doc["demo_order_execution_enabled"] is False


def test_stale_candle_cannot_generate_a_fake_quote_or_open_profit():
    stale=NOW-timedelta(minutes=6)
    doc=paper_desk.snapshot(ReadOnlyCursor(open_positions=True,bar_start=stale),now=NOW)
    assert doc["market"] is None
    assert doc["pulse"]["paper_open_unrealized_net"] is None
    assert doc["micro_engine"]["paper_bots"][0]["open_mark_source"]=="NO_FRESH_MARK"


def test_missing_stream_tables_are_named_without_legacy_scheduler():
    doc=paper_desk.snapshot(ReadOnlyCursor(missing=("stream_accounts","stream_trades")),now=NOW)
    assert doc["initialized"] is False
    assert doc["reason"]=="stream_schema_missing"
    assert "stream_trades" in doc["missing_tables"]
    assert doc["live_execution_enabled"] is False


def test_negative_short_mark_to_market_and_fee_applied():
    pos={"entry_price":64000.,"qty":0.1,"direction":"SHORT"}
    expected=(64000-65000)*0.1-65000*0.1*0.0003
    assert paper_desk._virtual_open_pnl(pos,65000)==round(expected,6)
    assert paper_desk._virtual_open_pnl({**pos,"direction":"UNKNOWN"},65000) is None


def test_desk_readiness_cannot_mutate_broker_or_trade():
    code=open("aegis/paper_desk.py",encoding="utf-8").read()
    assert "trade_send" not in code
    assert "place_order" not in code
    assert "CREATE TABLE" not in code


class Request:
    def __init__(self,path):
        self.path=path
        self.reply=None
    def _reply(self,status,data,cache="no-store"):
        self.reply=(status,data)


def test_desk_get_rejects_query_smuggling():
    req=Request("/api/stage3?desk=1&backtest=1")
    handler.do_GET(req)
    assert req.reply[0]==400
    assert req.reply[1]["error"]=="invalid_paper_desk_query"


def test_desk_get_is_independent_of_old_forward_tick(monkeypatch):
    expected={"ok":True,"mode":"KRAKEN_PAPER_SOURCE_BACKED","initialized":True}
    monkeypatch.setattr(paper_desk,"get_paper_desk",lambda:expected)
    req=Request("/api/stage3?desk=1")
    handler.do_GET(req)
    assert req.reply==(200,expected)
