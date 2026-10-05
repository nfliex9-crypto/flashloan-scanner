from aegis.live_lab import (
    Candle,
    compounded_return,
    evaluate_agent,
    max_drawdown,
    strategy_positions,
    strategy_returns,
)


def synthetic_candles(count=320):
    price = 100.0
    out = []
    for i in range(count):
        drift = 0.0012 if (i // 60) % 2 == 0 else -0.0003
        wave = ((i % 11) - 5) * 0.00015
        price *= 1.0 + drift + wave
        out.append(
            Candle(
                ts=1_700_000_000 + i * 3600,
                open=price * 0.999,
                high=price * 1.002,
                low=price * 0.998,
                close=price,
                volume=1000 + i,
            )
        )
    return out


def test_strategy_positions_match_length():
    closes = [c.close for c in synthetic_candles()]
    for name in ("Trend", "Momentum", "Mean Reversion", "Breakout"):
        assert len(strategy_positions(closes, name)) == len(closes)


def test_return_and_drawdown_metrics_are_valid():
    closes = [c.close for c in synthetic_candles()]
    positions = strategy_positions(closes, "Trend")
    returns = strategy_returns(closes, positions)
    assert len(returns) == len(closes)
    assert -1 < compounded_return(returns) < 10
    assert 0 <= max_drawdown(returns) <= 1


def test_agent_evaluation_has_real_metrics_shape():
    result = evaluate_agent("BTC", "Trend", synthetic_candles())
    assert result["status"] in {"ACTIVE", "PROBATION", "ELIMINATED"}
    assert result["trades"] >= 0
    assert 0 <= result["max_drawdown"] <= 1
    assert 0 <= result["survival_score"] <= 100
    assert result["latest_signal"] in {"LONG", "FLAT"}
    assert "cost_3x_positive" in result["stress"]
