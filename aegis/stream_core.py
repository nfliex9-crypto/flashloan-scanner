"""Causal public Kraken WebSocket v2 OHLC gate.

Updates are not fills. Only a NEW valid interval can seal the previous
candle; snapshots, duplicates, gaps, stale/future data must not trade.
This module contains no broker credentials, order endpoint, or I/O.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

from .live_lab import Candle

ALLOWED_MINUTES = (1, 5, 15, 60, 240, 1440, 10080)
SYMBOL_NAMES = {"BTC/USD": "BTC", "ETH/USD": "ETH"}


@dataclass(frozen=True)
class CompletedBar:
    symbol: str
    interval_minutes: int
    candle: Candle
    next_open: float
    next_start: int


def parse_kraken_bar(row: dict) -> tuple[str, int, Candle]:
    symbol = row.get("symbol")
    interval = row.get("interval")
    if symbol not in SYMBOL_NAMES or type(interval) is not int or interval not in ALLOWED_MINUTES:
        raise ValueError("Unsupported Kraken pair or candle interval")
    raw_start = str(row["interval_begin"])
    start = datetime.fromisoformat(raw_start.replace("Z", "+00:00"))
    if start.tzinfo is None:
        raise ValueError("Kraken interval_begin needs a timezone")
    ts = int(start.astimezone(timezone.utc).timestamp())
    seconds = interval * 60
    # Weekly source calendars need not be anchored to Unix epoch Thursday.
    # Consecutive weekly bars still must differ by exactly 604800 seconds.
    alignment=86400 if interval==10080 else seconds
    if ts % alignment or start.microsecond:
        raise ValueError("Unaligned Kraken interval")
    op, high, low, close = (float(row[k]) for k in ("open", "high", "low", "close"))
    volume = float(row.get("volume", 0))
    if not all(math.isfinite(x) and x > 0 for x in (op, high, low, close)):
        raise ValueError("Invalid Kraken OHLC")
    if not math.isfinite(volume) or volume < 0 or high < max(op, close) or low > min(op, close):
        raise ValueError("Inconsistent Kraken OHLC or volume")
    return SYMBOL_NAMES[symbol], interval, Candle(ts, op, high, low, close, volume)


class ClosedBarGate:
    """Tracks mutable current candles, emits only verified CLOSED OHLC."""

    def __init__(self) -> None:
        self.current: dict[tuple[str, int], Candle] = {}
        self.messages = 0
        self.rejected = 0
        self.gaps = 0

    def consume(self, message: dict, now: datetime) -> list[CompletedBar]:
        if now.tzinfo is None:
            raise ValueError("Feed clock must be timezone-aware")
        if message.get("channel") != "ohlc" or message.get("type") not in ("update", "snapshot"):
            return []
        rows = message.get("data")
        if not isinstance(rows, list):
            self.rejected += 1
            return []
        parsed = []
        for row in rows:
            try:
                parsed.append(parse_kraken_bar(row))
            except (ValueError, KeyError, TypeError, OverflowError):
                self.rejected += 1
        self.messages += 1
        # Snapshots may contain older bars; establishing a high water mark
        # must never manufacture paper results.
        if message["type"] == "snapshot":
            for sym, interval, candle in parsed:
                key = (sym, interval)
                if key not in self.current or candle.ts > self.current[key].ts:
                    self.current[key] = candle
            return []

        output: list[CompletedBar] = []
        for sym, interval, candle in sorted(parsed, key=lambda x: (x[0], x[1], x[2].ts)):
            key = (sym, interval)
            old = self.current.get(key)
            if old is None:
                self.current[key] = candle
                continue
            if candle.ts < old.ts:
                self.rejected += 1
                continue
            if candle.ts == old.ts:
                self.current[key] = candle
                continue
            self.current[key] = candle
            if candle.ts - old.ts != interval * 60:
                self.gaps += 1
                continue
            age = now.timestamp() - candle.ts
            if not (0 <= age < interval * 60):
                self.rejected += 1
                continue
            output.append(CompletedBar(sym, interval, old, candle.open, candle.ts))
        return output


def fresh_closed_history(candles: list[Candle], interval_minutes: int, minimum: int = 95) -> bool:
    """Protect against strategy signals computed across missing market bars."""
    if interval_minutes not in ALLOWED_MINUTES or len(candles) < minimum:
        return False
    seconds = interval_minutes * 60
    recent = candles[-minimum:]
    if not all(recent[i + 1].ts - recent[i].ts == seconds for i in range(len(recent) - 1)):
        return False
    return all(math.isfinite(c.close) and c.close > 0 for c in recent)
