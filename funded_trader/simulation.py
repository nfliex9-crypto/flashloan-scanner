"""Illustrative trade-path bootstrap. NOT a prediction or validated backtest."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from random import Random
from .rules import AccountState, RuleProfile, D

@dataclass(frozen=True)
class SimulationResult:
    trials: int
    passed: int
    failed: int
    unfinished: int
    pass_fraction: float

def bootstrap(paths: list[Decimal], profile: RuleProfile, trials: int = 1000,
              max_trades: int = 120, seed: int = 42) -> SimulationResult:
    if not paths or trials < 1 or max_trades < 1:
        raise ValueError("Provide observed net PnL outcomes and positive trials/trades")
    if any(not D(v).is_finite() for v in paths):
        raise ValueError("Non-finite outcomes")
    rand = Random(seed)
    passed = failed = 0
    start = datetime(2026, 1, 5, 23, 0, tzinfo=timezone.utc)
    for _ in range(trials):
        account = AccountState(profile)
        for i in range(max_trades):
            t = start + timedelta(days=i)
            account.close_trade(t, rand.choice(paths))
            if account.breached:
                failed += 1
                break
            if account.eligible:
                passed += 1
                break
    return SimulationResult(trials, passed, failed, trials - passed - failed,
                            passed / trials)
