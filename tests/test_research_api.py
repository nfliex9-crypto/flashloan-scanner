import unittest
from datetime import datetime,timedelta,timezone
from api.research import analyze
from funded_trader.rules import D

def bars_fixture():
    from zoneinfo import ZoneInfo
    et=ZoneInfo("America/New_York")
    base=datetime(2026,1,6,9,30,tzinfo=et)
    rows=[]
    for i in range(78):
        ts=(base+timedelta(minutes=5*i)).astimezone(timezone.utc)
        close = 6002 if i==6 else 6000
        h,l=(6015,6001) if i==7 else (6003,5999)
        rows.append({"t":ts.isoformat(),"o":6002 if i==7 else 6000,
                     "h":h,"l":l,"c":close if i!=7 else 6002,"v":100})
    return rows
class ResearchEndpointTests(unittest.TestCase):
    def test_analysis_returns_real_fixture_stats(self):
        report=analyze({"bars":bars_fixture(),"instrument":"MES","fee":2.5})
        self.assertEqual(report["bars"],78)
        self.assertEqual(report["trades"],1)
        self.assertGreater(float(report["net_pnl"]),0)
        self.assertFalse(report["verified_live_feed"])
    def test_bogus_fee_rejected(self):
        with self.assertRaises(ValueError):
            analyze({"bars":bars_fixture(),"instrument":"MES","fee":"NaN"})
    def test_unsupported_symbol_rejected(self):
        with self.assertRaises(ValueError):
            analyze({"bars":bars_fixture(),"instrument":"BTC","fee":2.5})
    def test_invalid_mode_rejected(self):
        with self.assertRaises(ValueError):
            analyze({"bars":bars_fixture(),"instrument":"MNQ","fee":2.5,"mode":"anything"})
    def test_size_bounded(self):
        with self.assertRaises(ValueError):
            analyze({"bars":[],"instrument":"MES","fee":2.5})
