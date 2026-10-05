from aegis.execution import (
    Level,
    OrderBook,
    buy_with_quote,
    book_microstructure,
    sell_quantity,
)


def book():
    return OrderBook(
        pair="XBTUSD",
        bids=(
            Level(99.0, 1.0),
            Level(98.0, 2.0),
        ),
        asks=(
            Level(101.0, 1.0),
            Level(102.0, 2.0),
        ),
    )


def test_buy_never_spends_more_than_cash():
    fill = buy_with_quote(book(), 100.0, fee_bps=80)
    assert fill.fully_filled
    assert abs(fill.gross_quote + fill.fee_quote) <= 100.000001
    assert fill.vwap >= 101.0
    assert fill.slippage_bps >= 0


def test_sell_consumes_bids_and_deducts_fee():
    fill = sell_quantity(book(), 1.5, fee_bps=80)
    assert fill.fully_filled
    assert fill.vwap <= 99.0
    assert fill.net_quote < fill.gross_quote
    assert fill.fee_quote > 0


def test_microstructure_has_realistic_shape():
    m = book_microstructure(book(), notional_quote=50.0)
    assert m["best_bid"] == 99.0
    assert m["best_ask"] == 101.0
    assert m["spread_bps"] > 0
    assert -1 <= m["book_imbalance"] <= 1
