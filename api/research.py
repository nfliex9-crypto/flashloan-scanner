"""Bounded, research-only Vercel API. No credentials, trading or remote data fetch.

POST own OHLCV bars to /api/research to run the exact Python research engine.
Never store payloads; outputs are hypothetical and require independent verification.
"""
from __future__ import annotations
import json
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler
from funded_trader.market_data import parse_projectx_bars
from funded_trader.backtest import run_orb
from funded_trader.rules import Contract, RuleProfile, D

MAX_BODY = 1_600_000
MAX_BARS = 7000
SYMBOLS = {"MES": (D("0.25"), D("1.25")), "MNQ": (D("0.25"), D("0.5"))}

def finite_decimal(x, *, positive=False, maximum=None):
    if isinstance(x, bool):
        raise ValueError("Boolean values are not amounts")
    try:
        n = D(x)
    except (TypeError,ValueError,InvalidOperation):
        raise ValueError("Invalid amount") from None
    if not n.is_finite() or (positive and n <= 0) or (maximum is not None and n > maximum):
        raise ValueError("Amount out of range")
    return n

def analyze(payload):
    if not isinstance(payload,dict):
        raise ValueError("Request must be a JSON object")
    raw=payload.get("bars")
    if not isinstance(raw,list) or not (1 <= len(raw) <= MAX_BARS):
        raise ValueError("Provide 1 to 7000 genuine bars")
    instrument=payload.get("instrument")
    if instrument not in SYMBOLS:
        raise ValueError("Only MES/MNQ instruments supported")
    bars=parse_projectx_bars(raw)
    if not bars:
        raise ValueError("No historical bars found")
    fee=finite_decimal(payload.get("fee"),maximum=D("100"))
    if fee < 0:
        raise ValueError("Fees cannot be negative")
    risk=finite_decimal(payload.get("risk",75),positive=True,maximum=D(1000))
    target=finite_decimal(payload.get("target",3000),positive=True,maximum=D(100000))
    starting=finite_decimal(payload.get("starting",50000),positive=True,maximum=D(10000000))
    limit=finite_decimal(payload.get("max_loss",2000),positive=True,maximum=D(1000000))
    daily=finite_decimal(payload.get("daily_limit",1200),positive=True,maximum=D(1000000))
    mode=payload.get("mode","eod_trailing")
    if mode not in ("eod_trailing","static","intraday_trailing"):
        raise ValueError("Invalid drawdown mode")
    rules=RuleProfile("Manual illustrative policy (NOT firm certified)",starting,limit,
        target,mode=mode,daily_loss_limit=daily,max_contracts=4)
    tick,value=SYMBOLS[instrument]
    contract=Contract(instrument,tick,value,fee)
    result=run_orb(bars,contract,rules,risk_budget=risk)
    return {
        "mode":"offline-historical-research",
        "verified_live_feed":False,
        "broker_connected":False,
        "performance_verified":False,
        "notice":"Uploaded bars are user-supplied. Backtest is hypothetical; bar-level fills and firm rules may differ.",
        "instrument":instrument,
        "bars":result.bars,
        "sessions":result.sessions,
        "skipped_sessions":result.skipped_sessions,
        "trades":len(result.trades),
        "long_trades":sum(1 for t in result.trades if t.side=="LONG"),
        "short_trades":sum(1 for t in result.trades if t.side=="SHORT"),
        "net_pnl":str(result.net_pnl),
        "ending_balance":str(result.ending_balance),
        "breached":result.breached,
        "target_met":result.target_met,
        "eligible_under_manual_rules":result.eligible,
        "trade_history":[{"side":t.side,"entry_time":t.entry_time.isoformat(),
            "exit_time":t.exit_time.isoformat(),"qty":t.quantity,
            "entry_price":str(t.entry),"exit_price":str(t.exit),
            "net_pnl":str(t.net_pnl),"reason":t.reason}
            for t in result.trades]
        }

class handler(BaseHTTPRequestHandler):
    def _send(self,status,payload):
        raw=json.dumps(payload,ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Content-Length",str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self._send(200,{"service":"Funded Trader AI research API",
            "trading_enabled":False,"data_feed_connected":False,
            "version":"0.2"})

    def do_POST(self):
        size=self.headers.get("Content-Length","")
        if not size.isdecimal() or not (0 < int(size) <= MAX_BODY):
            self._send(413,{"error":"Invalid or oversized request"});return
        try:
            payload=json.loads(self.rfile.read(int(size)))
            answer=analyze(payload)
        except (ValueError,TypeError,KeyError) as exc:
            self._send(400,{"error":str(exc)[:240]});return
        except Exception:
            self._send(500,{"error":"Research evaluation failed. Check input intervals and server logs."});return
        self._send(200,answer)
