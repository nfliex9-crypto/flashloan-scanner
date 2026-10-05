from aegis.execution import Level, OrderBook
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


def book(price=110.0):
    return OrderBook(
        pair="XBTUSD",
        bids=(
            Level(price - 0.5, 100.0),
            Level(price - 1.0, 100.0),
        ),
        asks=(
            Level(price + 0.5, 100.0),
            Level(price + 1.0, 100.0),
        ),
    )


def test_new_agent_uses_real_execution_shape():
    data = candles([100 + i * 0.2 for i in range(100)])
    agent = new_agent("BTC", "Trend", 0, data, book(120))
    assert agent["last_closed_ts"] == data[-1].ts
    assert agent["equity"] > 0
    assert agent["position"] in {0, 1}
    assert "total_fees_usd" in agent
    assert "total_slippage_usd" in agent


def test_same_closed_bar_is_not_processed_twice():
    base = candles([100 + i * 0.1 for i in range(100)])
    agent = new_agent("BTC", "Trend", 0, base, book(110))

    extended = candles([100 + i * 0.1 for i in range(101)])
    first = advance_agent(agent, "Trend", 0, extended, book(111))
    updates_after = agent["updates"]
    second = advance_agent(agent, "Trend", 0, extended, book(111))

    assert first is True
    assert second is False
    assert agent["updates"] == updates_after


def test_gap_does_not_backfill_fake_historical_fills():
    base = candles([100 + i * 0.1 for i in range(100)])
    agent = new_agent("BTC", "Trend", 0, base, book(110))

    extended = candles([100 + i * 0.1 for i in range(105)])
    advance_agent(agent, "Trend", 0, extended, book(112))

    assert agent["missed_bar_events"] >= 1
    assert agent["last_closed_ts"] == extended[-1].ts


def test_forward_drawdown_is_bounded():
    base = candles([100 + i * 0.2 for i in range(100)])
    agent = new_agent("BTC", "Trend", 0, base, book(120))
    extended = candles([100 + i * 0.2 for i in range(101)])
    advance_agent(agent, "Trend", 0, extended, book(115))
    assert 0 <= agent["max_drawdown"] <= 1
