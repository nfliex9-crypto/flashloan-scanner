"""Gold Squad fail-closed contracts. No account keys and no external requests."""
from datetime import datetime, timedelta, timezone
import pytest

from aegis.gold_lab import (
    GOLD_SYMBOL, MIN_CLOSED_BARS, gold_agents,
    normalize_gold_candles,
)
from aegis.paper_engine import RiskConfig, _position_size


def gold_fixture(*, bars=230, now=None, remove_index=None):
    now = now or datetime(2026, 10, 8, 10, 5, tzinfo=timezone.utc)
    current = now.replace(minute=0, second=0, microsecond=0)
    records = []
    for i in range(bars):
        if i == remove_index:
            continue
        stamp = current - timedelta(hours=bars - 1 - i)
        price = 4010 + i * 0.35
        records.append({"datetime": stamp.strftime("%Y-%m-%d %H:%M:%S"),
                        "open": str(price), "high": str(price + 1),
                        "low": str(price - 1), "close": str(price + .2)})
    return {"values": list(reversed(records))}, now


def test_gold_closed_candles_exclude_current_open_bar():
    p, now = gold_fixture()
    closed, current = normalize_gold_candles(p, now)
    assert len(closed) == 229
    assert closed[-1].ts + 3600 == current.ts
    assert current.ts + 3600 > now.timestamp()
    assert all(c.ts + 3600 <= now.timestamp() for c in closed)


def test_gold_agents_are_four_shadow_only():
    p, now = gold_fixture()
    closed, _ = normalize_gold_candles(p, now)
    agents = gold_agents(closed)
    assert len(agents) == 4
    assert len({a["agent_id"] for a in agents}) == 4
    assert all(a["asset"] == GOLD_SYMBOL and a["shadow_only"] for a in agents)


def test_stale_quote_never_enters_shadow():
    p, now = gold_fixture()
    with pytest.raises(ValueError, match="stale|closed"):
        normalize_gold_candles(p, now + timedelta(hours=3))


def test_missing_most_recent_completed_candle_fails_closed():
    p, now = gold_fixture(remove_index=228)
    with pytest.raises(ValueError, match="contiguous"):
        normalize_gold_candles(p, now)


def test_rejects_false_gold_ohlc():
    p, now = gold_fixture()
    p["values"][0]["high"] = "-2"
    with pytest.raises(ValueError, match="Invalid"):
        normalize_gold_candles(p, now)


def test_shadow_gold_risk_size_is_bounded():
    cfg = RiskConfig(risk_per_trade=.0025, max_position_notional_pct=.20,
                     fee_bps_per_side=3, slippage_bps_per_side=5)
    qty, risk, notional = _position_size(100000, 4000, 3970, cfg)
    assert risk <= 250
    assert qty * 30 <= 250
    assert notional <= 20000
