"""Conservative ORB research simulator for futures.

Completed-bar signal -> *next bar* open (no same-bar look-ahead).
RTH only (09:30–16:00 America/New_York); one trade per session.
Stop wins when both stop and target touch a bar; open gaps use worse fill.
No broker, data scraping, real execution or claimed predictive edge.
"""
from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo
from .market_data import Bar
from .rules import AccountState, Contract, RuleProfile, D, size_position

NEW_YORK = ZoneInfo("America/New_York")

@dataclass(frozen=True)
class BacktestTrade:
    side: str
    entry_time: datetime
    exit_time: datetime
    quantity: int
    entry: Decimal
    exit: Decimal
    net_pnl: Decimal
    reason: str

@dataclass(frozen=True)
class BacktestReport:
    bars: int
    sessions: int
    trades: tuple[BacktestTrade, ...]
    ending_balance: Decimal
    net_pnl: Decimal
    breached: bool
    target_met: bool
    eligible: bool
    skipped_sessions: int
    drawdown_mode: str

def _pnl(side: int, entry: Decimal, exit: Decimal, quantity: int, c: Contract) -> Decimal:
    return ((exit-entry) * side / c.tick_size * c.tick_value - c.roundtrip_fee) * quantity

def _time(b: Bar) -> time:
    return b.time.astimezone(NEW_YORK).time().replace(tzinfo=None)

def run_orb(bars: list[Bar], contract: Contract, profile: RuleProfile, *,
            risk_budget: Decimal = D(75), stop_ticks: int = 20,
            target_ticks: int = 40, slippage_ticks: int = 1) -> BacktestReport:
    """An exploratory baseline. Bars MUST be five-minute, bar-start timestamped."""
    if not bars:
        raise ValueError("No real data was provided")
    if stop_ticks < 1 or target_ticks < 1 or slippage_ticks < 0 or D(risk_budget) <= 0:
        raise ValueError("Invalid simulator parameters")
    if any(b.time >= bars[i+1].time for i,b in enumerate(bars[:-1])):
        raise ValueError("Bars must be strictly chronological with no duplicates")
    account = AccountState(profile)
    days: dict[str,list[Bar]] = defaultdict(list)
    for b in bars:
        days[b.time.astimezone(NEW_YORK).date().isoformat()].append(b)
    trades:list[BacktestTrade] = []
    skipped = 0
    slip = contract.tick_size * slippage_ticks
    for session, samples in sorted(days.items()):
        if account.breached or account.eligible:
            break
        rth = [b for b in samples if time(9,30) <= _time(b) < time(16,0)]
        opening = [b for b in rth if time(9,30) <= _time(b) < time(10,0)]
        expected = [time(9,30),time(9,35),time(9,40),time(9,45),time(9,50),time(9,55)]
        if len(opening) != 6 or [_time(b) for b in opening] != expected:
            skipped += 1
            continue
        # Safety: incomplete/mixed-frequency RTH data cannot be used for a 5-minute model.
        if any((rth[k+1].time-rth[k].time) != timedelta(minutes=5) for k in range(len(rth)-1)):
            skipped += 1
            continue
        top = max(b.high for b in opening)
        bottom = min(b.low for b in opening)
        prev_close = opening[-1].close
        for i in range(6,len(rth)-1):
            signal = rth[i]
            nextbar = rth[i+1]
            if _time(signal) >= time(15,0):
                break
            # signal evaluates a COMPLETED bar; fill is at nextbar OPEN
            side = 1 if prev_close <= top and signal.close > top else (-1 if prev_close >= bottom and signal.close < bottom else 0)
            prev_close = signal.close
            if side == 0:
                continue
            account.observe_equity(nextbar.time, D(0))
            decision = size_position(account, contract, contract.tick_size * stop_ticks,
                                     risk_budget, slippage_ticks=slippage_ticks)
            if not decision.approved:
                continue
            qty = decision.quantity
            entry = nextbar.open + slip * side
            stop = entry - side * contract.tick_size * stop_ticks
            target = entry + side * contract.tick_size * target_ticks
            exit_price = None
            exit_time = None
            reason = "SESSION_CLOSE"
            for b in rth[i+1:]:
                # Intrabar sequence unknown: mark favorable first, then adverse,
                # which is conservative for trailing intraday drawdown.
                favorable = b.high if side == 1 else b.low
                adverse = b.low if side == 1 else b.high
                account.observe_equity(b.time, _pnl(side,entry,favorable,qty,contract))
                account.observe_equity(b.time, _pnl(side,entry,adverse,qty,contract))
                hit_stop = (b.low <= stop) if side == 1 else (b.high >= stop)
                hit_target = (b.high >= target) if side == 1 else (b.low <= target)
                if hit_stop:
                    # Opposite direction fills at or beyond stop after a gap.
                    exit_price = (min(b.open,stop)-slip) if side == 1 else (max(b.open,stop)+slip)
                    reason = "STOP" if not hit_target else "STOP_FIRST_AMBIGUOUS"
                elif hit_target:
                    exit_price = (target-slip) if side == 1 else (target+slip)
                    reason = "TARGET"
                elif _time(b) >= time(15,55) or b is rth[-1]:
                    exit_price = b.close - side*slip
                if exit_price is not None:
                    exit_time = b.time
                    break
            if exit_price is None or exit_time is None:
                raise RuntimeError("No valid exit price")
            realized = _pnl(side,entry,exit_price,qty,contract)
            account.close_trade(exit_time,realized)
            trades.append(BacktestTrade("LONG" if side==1 else "SHORT",nextbar.time,
                          exit_time,qty,entry,exit_price,realized,reason))
            break  # max one trade per RTH session
    return BacktestReport(len(bars),len(days),tuple(trades),account.balance,
            account.net_profit,account.breached,account.target_met,
            account.eligible,skipped,profile.mode)
