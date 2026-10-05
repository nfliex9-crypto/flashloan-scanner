from __future__ import annotations

from aegis.execution import book_microstructure, fetch_order_book
from aegis.live_lab import ASSETS, fetch_ohlc


def main() -> None:
    for symbol, pair in ASSETS.items():
        candles = fetch_ohlc(pair, 15, closed_only=True)
        assert len(candles) >= 120
        assert candles[-1].close > 0

        book = fetch_order_book(pair, 25)
        micro = book_microstructure(book, notional_quote=1_000.0)

        assert micro["best_bid"] > 0
        assert micro["best_ask"] > micro["best_bid"]
        assert micro["spread_bps"] >= 0
        assert -1.0 <= micro["book_imbalance"] <= 1.0

        print(
            symbol,
            "bars=", len(candles),
            "bid=", micro["best_bid"],
            "ask=", micro["best_ask"],
            "spread_bps=", round(micro["spread_bps"], 4),
        )


if __name__ == "__main__":
    main()
