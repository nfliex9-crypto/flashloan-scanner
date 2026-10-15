import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from funded_trader.market_data import Bar
from funded_trader.backtest import run_orb
from funded_trader.rules import Contract,RuleProfile,D

NY=ZoneInfo("America/New_York")
def sample_day(start="2026-01-06", direction="up", both=False):
    base=datetime.fromisoformat(start+"T09:30:00").replace(tzinfo=NY)
    out=[]
    for i in range(78):
        ts=(base+timedelta(minutes=5*i)).astimezone(timezone.utc)
        op=D(6000)
        hi=D(6001)
        lo=D(5999)
        close=D(6000)
        if i==6:
            close=D(6002 if direction=="up" else 5998)
            hi=max(hi,close)
            lo=min(lo,close)
        if i==7:
            op=D(6002 if direction=="up" else 5998)
            hi=D(6015 if direction=="up" else 6000)
            lo=D(5995 if both else (6001 if direction=="up" else 5985))
            close=op
        out.append(Bar(ts,op,hi,lo,close,D(50)))
    return out
def rules():
    return RuleProfile("TEST",D(50000),D(2000),D(3000),mode="static",daily_loss_limit=None)
c=Contract("MES",D(".25"),D("1.25"),D("2.5"))
class BacktestTests(unittest.TestCase):
    def test_next_bar_fill_and_one_trade(self):
        bars=sample_day()
        report=run_orb(bars,c,rules(),stop_ticks=20,target_ticks=40,slippage_ticks=1)
        self.assertEqual(len(report.trades),1)
        t=report.trades[0]
        self.assertEqual(t.entry_time,bars[7].time)
        self.assertEqual(t.entry,D("6002.25"))
        self.assertEqual(t.side,"LONG")
        self.assertEqual(t.reason,"TARGET")
        self.assertGreater(t.net_pnl,0)
    def test_short_and_costs(self):
        result=run_orb(sample_day(direction="down"),c,rules(),stop_ticks=20,target_ticks=40)
        self.assertEqual(result.trades[0].side,"SHORT")
        self.assertGreater(result.trades[0].net_pnl,0)
    def test_stop_first_on_ambiguous_bar(self):
        result=run_orb(sample_day(both=True),c,rules(),stop_ticks=20,target_ticks=40)
        self.assertEqual(result.trades[0].reason,"STOP_FIRST_AMBIGUOUS")
        self.assertLess(result.trades[0].net_pnl,0)
    def test_no_incomplete_opening_range(self):
        bars=sample_day()[1:]
        result=run_orb(bars,c,rules())
        self.assertEqual(len(result.trades),0)
        self.assertEqual(result.skipped_sessions,1)
    def test_empty_rejected(self):
        with self.assertRaises(ValueError):run_orb([],c,rules())
    def test_refuse_unordered(self):
        bars=sample_day()
        with self.assertRaises(ValueError):run_orb(bars[::-1],c,rules())
