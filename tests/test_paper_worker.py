from aegis.live_lab import Candle
from aegis.paper_worker import advance_agent, new_agent


def candles(prices):
    return [
        Candle(
            ts=1_700_000_000 + i * 900,
            open=p,
            high=p * 1.001,
            low=p * 0.999,
            close=p,
            volume=1000,
        )
        for i, p in enumerate(prices)
    ]


def test_new_agent_starts_at_latest_closed_bar():
    data = candles([100 + i * 0.1 for i in range(100)])
    agent = new_agent("BTC", "Trend", 0, data)
    assert agent["last_closed_ts"] == data[-1].ts
    assert agent["equity"] > 0
    assert agent["position"] in {0, 1}


def test_same_candle_is_not_processed_twice():
    base = candles([100 + i * 0.1 for i in range(100)])
    agent = new_agent("BTC", "Trend", 0, base)

    extended = candles([100 + i * 0.1 for i in range(102)])
    first = advance_agent(agent, "Trend", 0, extended)
    updates_after = agent["updates"]
    second = advance_agent(agent, "Trend", 0, extended)

    assert first is True
    assert second is False
    assert agent["updates"] == updates_after


def test_forward_drawdown_is_bounded():
    base = candles([100 + i * 0.2 for i in range(100)])
    agent = new_agent("BTC", "Trend", 0, base)
    extended = candles(
        [100 + i * 0.2 for i in range(100)]
        + [119, 117, 114, 111, 109]
    )
    advance_agent(agent, "Trend", 0, extended)
    assert 0 <= agent["max_drawdown"] <= 1
