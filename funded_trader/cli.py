"""Local, read-only data ingestion and offline ORB research.
python -m funded_trader.cli contracts MES
python -m funded_trader.cli fetch CON.F.US.MES.<current> 2026-10-01T00:00:00+00:00 2026-10-02T00:00:00+00:00 data/mes.csv
python -m funded_trader.cli backtest data/mes.csv --instrument MES --fee 2.50
"""
import argparse
import json
import sys
from datetime import timezone
from decimal import Decimal
from pathlib import Path
from .market_data import ProjectXReadOnly, timestamp_utc, store_bars, read_bars_csv
from .backtest import run_orb
from .rules import Contract, D, example_profile, RuleProfile

CONTRACTS = {"MES": (D("0.25"), D("1.25")),
             "MNQ": (D("0.25"), D("0.50"))}

def main(argv=None):
    p=argparse.ArgumentParser(prog="funded-trader",description="Data-only ProjectX and offline futures backtesting; no orders")
    sub=p.add_subparsers(dest="action",required=True)
    co=sub.add_parser("contracts", help="Search active ProjectX simulated-feed contracts")
    co.add_argument("text",help="MES or MNQ")
    fe=sub.add_parser("fetch",help="Retrieve real provider 5m historical bars read-only")
    fe.add_argument("contract_id",help="Actual available contract ID, never guess expiration")
    fe.add_argument("start",help="ISO-8601 with timezone")
    fe.add_argument("end",help="ISO-8601 with timezone")
    fe.add_argument("output",help="CSV path")
    fe.add_argument("--minutes",type=int,default=5)
    bt=sub.add_parser("backtest",help="Offline, rule-aware ORB baseline")
    bt.add_argument("csv")
    bt.add_argument("--instrument",choices=tuple(CONTRACTS),required=True)
    bt.add_argument("--fee",type=Decimal,required=True,help="Round-trip commissions+exchange fees PER CONTRACT in USD")
    bt.add_argument("--risk",type=Decimal,default=D(75))
    bt.add_argument("--stop-ticks",type=int,default=20)
    bt.add_argument("--target-ticks",type=int,default=40)
    bt.add_argument("--slippage-ticks",type=int,default=1)
    args=p.parse_args(argv)
    if args.action in ("contracts","fetch"):
        client=ProjectXReadOnly.from_environment()
        client.authenticate()
        if args.action=="contracts":
            records=client.search_contracts(args.text)
            print(json.dumps([{"id":x.get("id"),"name":x.get("name"),
               "active":x.get("activeContract"),"tick_size":x.get("tickSize"),
               "tick_value":x.get("tickValue")} for x in records],indent=2))
        else:
            bars=client.retrieve_bars(args.contract_id,timestamp_utc(args.start),
                    timestamp_utc(args.end),minutes=args.minutes)
            if not bars: raise ValueError("Provider returned no bars; no synthetic data created")
            provenance=store_bars(args.output,bars,contract_id=args.contract_id,
                    source="ProjectX / TopstepX historical SIM market data",interval_minutes=args.minutes)
            print(json.dumps(provenance,indent=2))
        return 0
    if args.fee < 0:
        raise ValueError("Fees must be nonnegative")
    bars=read_bars_csv(args.csv)
    tick,tick_value=CONTRACTS[args.instrument]
    instrument=Contract(args.instrument,tick,tick_value,args.fee)
    report=run_orb(bars,instrument,example_profile(),risk_budget=args.risk,
        stop_ticks=args.stop_ticks,target_ticks=args.target_ticks,
        slippage_ticks=args.slippage_ticks)
    meta_path=Path(args.csv).with_suffix(Path(args.csv).suffix+".provenance.json")
    print(json.dumps({"mode":"offline-research-only","bars":report.bars,
      "sessions":report.sessions,"skipped_sessions":report.skipped_sessions,
      "trades":len(report.trades),"net_pnl_usd":str(report.net_pnl),
      "ending_balance_usd":str(report.ending_balance),
      "breached":report.breached,"evaluation_target_met":report.target_met,
      "eligible_under_illustrative_rules":report.eligible,
      "data_provenance_file_present":meta_path.exists(),
      "trades_detail":[{"side":t.side,"entry":t.entry_time.isoformat(),
        "exit":t.exit_time.isoformat(),"qty":t.quantity,"pnl":str(t.net_pnl),
        "reason":t.reason} for t in report.trades]},indent=2))
    return 0

if __name__=="__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, RuntimeError) as e:
        print("ERROR: "+str(e),file=sys.stderr)
        sys.exit(1)
