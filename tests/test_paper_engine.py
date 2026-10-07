from aegis.live_lab import Candle
from aegis.paper_engine import RiskConfig, _position_size, simulate_agent


def _trend_candles(n: int = 140) -> list[Candle]:
    rows = []
    price = 100.0
    for i in range(n):
        price += 0.35
        rows.append(
            Candle(
                ts=1_700_000_000 + i * 3600,
                open=price - 0.10,
                high=price + 0.30,
                low=price - 0.30,
                close=price,
                volume=1000.0 + i,
            )
        )
    return rows


def test_position_size_respects_risk_and_notional_caps():
    cfg = RiskConfig(
        starting_equity=10_000,
        risk_per_trade=0.0025,
        max_position_notional_pct=0.20,
    )
    qty, risk_budget, notional = _position_size(10_000, 100, 98, cfg)

    assert risk_budget == 25
    assert qty <= 12.5
    assert notional <= 2_000


def test_active_agent_can_create_paper_position_without_live_execution():
    cfg = RiskConfig(starting_equity=10_000)
    result = simulate_agent(
        symbol="BTC",
        strategy="Trend",
        candles=_trend_candles(),
        status="ACTIVE",
        survival_score=80.0,
        allocation=10_000,
        variant=0,
        config=cfg,
    )

    assert result["status"] == "ACTIVE"
    assert result["latest_signal"] == "LONG"
    assert result["open_position"] is not None or result["trade_count"] >= 1

    if result["open_position"] is not None:
        notionals = [result["open_position"]["notional"]]
    else:
        notionals = [trade["notional"] for trade in result["trades"]]

    assert notionals
    assert max(notionals) <= 10_000 * cfg.max_position_notional_pct + 1e-9


def test_probation_agent_generates_ghost_not_order():
    cfg = RiskConfig(starting_equity=10_000)
    result = simulate_agent(
        symbol="BTC",
        strategy="Trend",
        candles=_trend_candles(),
        status="PROBATION",
        survival_score=55.0,
        allocation=0.0,
        variant=0,
        config=cfg,
    )

    assert result["trade_count"] == 0
    assert result["open_position"] is None
    assert len(result["ghosts"]) >= 1
