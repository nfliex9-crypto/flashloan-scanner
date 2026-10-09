"""The web control room must describe actual recorded decisions, not render guesses."""
from datetime import datetime,timezone
from types import SimpleNamespace

import pytest
from aegis.stream_core import CompletedBar
from aegis.live_lab import Candle
from aegis.stream_paper import journal_decision


class LedgerCursor:
    def __init__(self):self.queries=[]
    def execute(self,statement,values):self.queries.append((statement,values))


def test_audit_wait_enter_exit_veto_and_mark_from_closed_market_bar():
    cur=LedgerCursor()
    candle=Candle(ts=1791522000,open=110,high=111,low=109,close=110,volume=1)
    event=CompletedBar("BTC",1,candle,111,1791522060)
    for action in ("WAIT","MARK","ENTER","EXIT","VETO"):
        journal_decision(cur,aid="micro-btc-1m-ema-cross",event=event,
            strategy="EMA Cross",direction="LONG",action=action,
            reason="CLOSED_BAR_ENTRY_SIGNAL" if action=="ENTER" else "NO_FRESH_CLOSED_BAR_ENTRY",
            reference_price=110,qty=.1 if action=="ENTER" else None)
    assert len(cur.queries)==5
    assert all("ON CONFLICT(agent_id,bar_start) DO NOTHING" in q for q,_ in cur.queries)
    assert all("INSERT INTO aegis.stream_decisions" in q for q,_ in cur.queries)
    assert all(args[2]=="BTC" for _,args in cur.queries)
    assert all(args[3]==1 for _,args in cur.queries)
    assert [values[6] for _,values in cur.queries]==["WAIT","MARK","ENTER","EXIT","VETO"]


def test_rejects_unknown_audit_action_without_side_effects():
    cur=LedgerCursor()
    bar=Candle(ts=1791522000,open=100,high=101,low=99,close=100,volume=1)
    event=CompletedBar("BTC",5,bar,101,1791522300)
    with pytest.raises(ValueError,match="Unknown auditable"):
        journal_decision(cur,aid="a",event=event,strategy="EMA Cross",
                         direction="LONG",action="REAL_ORDER",
                         reason="bad",reference_price=101)
    assert not cur.queries
