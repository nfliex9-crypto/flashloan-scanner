import csv
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from funded_trader.market_data import (ProjectXReadOnly,FeedError,parse_projectx_bars,
          read_bars_csv,store_bars, timestamp_utc, money)

class FakeResponse:
    def __init__(self,data): self.data=data
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def read(self):
        import json
        return json.dumps(self.data).encode("utf-8")

class MarketDataTests(unittest.TestCase):
    def test_utc_and_reject_naive(self):
        self.assertEqual(timestamp_utc("2026-01-05T09:00:00+01:00").hour,8)
        with self.assertRaises(ValueError): timestamp_utc("2026-01-05T09:00:00")
    def test_reject_impossible_and_duplicate(self):
        row={"t":"2026-01-05T10:00:00Z","o":100,"h":110,"l":90,"c":105,"v":2}
        bars=parse_projectx_bars([row])
        self.assertEqual(len(bars),1)
        with self.assertRaises(ValueError): parse_projectx_bars([row,row])
        with self.assertRaises(ValueError): parse_projectx_bars([{**row,"h":99}])
        with self.assertRaises(ValueError): money("NaN")
    def test_roundtrip_and_provenance(self):
        rows=[{"t":"2026-01-05T10:00:00Z","o":100,"h":110,"l":90,"c":105,"v":1}]
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"sample.csv"
            metadata=store_bars(path,parse_projectx_bars(rows),
                  contract_id="CON.F.US.MES.H26",source="unit-test fixture",interval_minutes=5)
            self.assertEqual(read_bars_csv(path),parse_projectx_bars(rows))
            self.assertEqual(metadata["row_count"],1)
            self.assertTrue(path.with_suffix(".csv.provenance.json").exists())
    def test_adapter_is_only_readonly(self):
        client=ProjectXReadOnly("user","secret")
        sent=[]
        def fake_urlopen(req,timeout):
            import json
            sent.append((req.full_url,req.headers, json.loads(req.data.decode())))
            if req.full_url.endswith("loginKey"):
                return FakeResponse({"success":True,"errorCode":0,"token":"token"})
            if req.full_url.endswith("retrieveBars"):
                return FakeResponse({"success":True,"errorCode":0,"bars":[
                   {"t":"2026-01-05T00:00:00Z","o":100,"h":100,"l":100,"c":100,"v":1}]})
            raise AssertionError("unexpected call")
        with patch("funded_trader.market_data.urlopen",side_effect=fake_urlopen):
            client.authenticate()
            r=client.retrieve_bars("CON.F.US.MES.H26",
                 timestamp_utc("2026-01-01T00:00:00Z"),timestamp_utc("2026-01-06T00:00:00Z"))
        self.assertEqual(len(r),1)
        self.assertFalse(sent[-1][2]["live"])
        self.assertFalse(sent[-1][2]["includePartialBar"])
        self.assertTrue(all("Order/" not in row[0] for row in sent))
        with self.assertRaises(FeedError):
            client._post("/api/Order/place",{"size":1})
    def test_api_body_failure_even_http_200(self):
        with patch("funded_trader.market_data.urlopen",return_value=FakeResponse(
                {"success":False,"errorCode":9,"errorMessage":"x"})):
            with self.assertRaisesRegex(FeedError,"9"):
                ProjectXReadOnly("user","bad_key").authenticate()
