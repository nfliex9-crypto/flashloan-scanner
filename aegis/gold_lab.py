"""Hourly XAU/USD research input with strict closed-bar / provider-time guards.

Twelve Data OHLC prices are indicative market observations, not executable
OANDA broker fills. Gold research is SHADOW-ONLY; no live broker API.
"""
from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from .live_lab import Candle, evaluate_agent

STRATEGIES = ("Trend", "Momentum", "Mean Reversion", "Breakout")
GOLD_SYMBOL = "XAU"
SECONDS_PER_BAR = 3600
MIN_CLOSED_BARS = 200
# Gold CFD proxy: conservative modeled execution cost, NOT broker-verified.
GOLD_FEE_BPS_PER_SIDE = 3.0
GOLD_SLIPPAGE_BPS_PER_SIDE = 5.0


def normalize_gold_candles(payload: dict, now: datetime) -> tuple[list[Candle], Candle]:
    """Return only fully closed 1h candles and an observed current-bar mark."""
    if payload.get("status") == "error":
        raise ValueError("Twelve Data denied gold OHLC request")
    rows = payload.get("values")
    if not isinstance(rows, list) or len(rows) < MIN_CLOSED_BARS:
        raise ValueError("Insufficient Twelve Data XAU/USD hourly history")

    bars = {}
    for row in rows:
        stamp = datetime.fromisoformat(str(row["datetime"]).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        stamp = stamp.astimezone(timezone.utc)
        ts = int(stamp.timestamp())
        prices = [float(row[x]) for x in ("open", "high", "low", "close")]
        op, hi, lo, close = prices
        if not all(math.isfinite(x) and x > 0 for x in prices):
            raise ValueError("Invalid gold OHLC")
        if not lo <= min(op, close) <= max(op, close) <= hi:
            raise ValueError("Inconsistent gold OHLC range")
        if ts in bars:
            raise ValueError("Duplicate gold candle timestamp")
        bars[ts] = Candle(ts=ts, open=op, high=hi, low=lo, close=close,
                          volume=float(row.get("volume") or 0))

    ordered = sorted(bars.values(), key=lambda c: c.ts)
    current = ordered[-1]
    now_ts = now.astimezone(timezone.utc).timestamp()
    # An in-progress candle MUST exist, refer to the current UTC hour, and
    # never be inferred from an old final bar (weekends / holidays / outages).
    if not (0 <= now_ts - current.ts < SECONDS_PER_BAR):
        raise ValueError("Gold feed is stale or market is closed; no entry")
    closed = [c for c in ordered[:-1] if c.ts + SECONDS_PER_BAR <= now_ts]
    if len(closed) < MIN_CLOSED_BARS:
        raise ValueError("Insufficient fully closed gold hourly candles")
    if closed[-1].ts + SECONDS_PER_BAR != current.ts:
        raise ValueError("Gold latest closed bar not contiguous with current quote")
    return closed, current


def fetch_gold_research(now: datetime) -> tuple[list[Candle], Candle]:
    key = os.getenv("TWELVEDATA_API_KEY")
    if not key:
        raise ValueError("TWELVEDATA_API_KEY not configured")
    query = urllib.parse.urlencode({
        "symbol": "XAU/USD", "interval": "1h", "outputsize": "260",
        "timezone": "UTC", "apikey": key,
    })
    request = urllib.request.Request(
        "https://api.twelvedata.com/time_series?" + query,
        headers={"User-Agent": "AEGIS-Gold-Shadow-Research/1.0"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=13) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        raise ValueError("Gold hourly data temporarily unavailable") from exc
    return normalize_gold_candles(payload, now)


def gold_agents(closed: list[Candle]) -> list[dict]:
    agents = []
    for index, strategy in enumerate(STRATEGIES):
        agent = evaluate_agent(GOLD_SYMBOL, strategy, closed, variant=index % 2)
        # No Gold agent is eligible for paper-main, even when the
        # historical research classifier labels it ACTIVE.
        agent["shadow_only"] = True
        agent["market_source"] = "Twelve Data XAU/USD 1h indicative"
        agents.append(agent)
    return agents
