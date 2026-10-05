from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass


KRAKEN_DEPTH_URL = "https://api.kraken.com/0/public/Depth"
DEFAULT_TAKER_FEE_BPS = float(os.getenv("AEGIS_TAKER_FEE_BPS", "80"))
DEFAULT_DEPTH = int(os.getenv("AEGIS_ORDERBOOK_DEPTH", "100"))


@dataclass(frozen=True)
class Level:
    price: float
    quantity: float


@dataclass(frozen=True)
class OrderBook:
    pair: str
    bids: tuple[Level, ...]
    asks: tuple[Level, ...]


@dataclass(frozen=True)
class Fill:
    side: str
    requested: float
    filled_quantity: float
    gross_quote: float
    fee_quote: float
    net_quote: float
    vwap: float
    best_price: float
    slippage_bps: float
    levels_used: int
    fully_filled: bool

    def to_dict(self) -> dict:
        return asdict(self)


def fetch_order_book(pair: str, count: int = DEFAULT_DEPTH) -> OrderBook:
    query = urllib.parse.urlencode({"pair": pair, "count": count})
    request = urllib.request.Request(
        f"{KRAKEN_DEPTH_URL}?{query}",
        headers={"User-Agent": "AEGIS-Execution-Sim/1.0"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))

    if payload.get("error"):
        raise RuntimeError(f"Kraken depth error: {payload['error']}")

    result = payload["result"]
    key = next(iter(result))
    raw = result[key]

    bids = tuple(Level(float(row[0]), float(row[1])) for row in raw["bids"])
    asks = tuple(Level(float(row[0]), float(row[1])) for row in raw["asks"])

    if not bids or not asks:
        raise RuntimeError("Kraken returned an empty order book")

    return OrderBook(pair=pair, bids=bids, asks=asks)


def buy_with_quote(
    book: OrderBook,
    cash_quote: float,
    *,
    fee_bps: float = DEFAULT_TAKER_FEE_BPS,
) -> Fill:
    """Spend at most cash_quote, consuming asks from best to worst."""
    if cash_quote <= 0:
        raise ValueError("cash_quote must be positive")

    fee_rate = fee_bps / 10_000.0
    max_gross_quote = cash_quote / (1.0 + fee_rate)
    remaining_quote = max_gross_quote

    quantity = 0.0
    gross_quote = 0.0
    levels_used = 0

    for level in book.asks:
        if remaining_quote <= 1e-12:
            break
        available_quote = level.price * level.quantity
        take_quote = min(remaining_quote, available_quote)
        take_qty = take_quote / level.price

        quantity += take_qty
        gross_quote += take_quote
        remaining_quote -= take_quote
        levels_used += 1

    fee_quote = gross_quote * fee_rate
    total_cost = gross_quote + fee_quote
    vwap = gross_quote / quantity if quantity > 0 else 0.0
    best = book.asks[0].price
    slippage = ((vwap / best) - 1.0) * 10_000 if vwap and best else 0.0

    return Fill(
        side="BUY",
        requested=cash_quote,
        filled_quantity=quantity,
        gross_quote=gross_quote,
        fee_quote=fee_quote,
        net_quote=-total_cost,
        vwap=vwap,
        best_price=best,
        slippage_bps=slippage,
        levels_used=levels_used,
        fully_filled=(remaining_quote <= max(1e-8, max_gross_quote * 1e-8)),
    )


def sell_quantity(
    book: OrderBook,
    quantity: float,
    *,
    fee_bps: float = DEFAULT_TAKER_FEE_BPS,
) -> Fill:
    """Sell base quantity, consuming bids from best to worst."""
    if quantity <= 0:
        raise ValueError("quantity must be positive")

    remaining_qty = quantity
    filled_qty = 0.0
    gross_quote = 0.0
    levels_used = 0

    for level in book.bids:
        if remaining_qty <= 1e-12:
            break
        take_qty = min(remaining_qty, level.quantity)
        filled_qty += take_qty
        gross_quote += take_qty * level.price
        remaining_qty -= take_qty
        levels_used += 1

    fee_rate = fee_bps / 10_000.0
    fee_quote = gross_quote * fee_rate
    net_quote = gross_quote - fee_quote
    vwap = gross_quote / filled_qty if filled_qty > 0 else 0.0
    best = book.bids[0].price
    slippage = ((best - vwap) / best) * 10_000 if vwap and best else 0.0

    return Fill(
        side="SELL",
        requested=quantity,
        filled_quantity=filled_qty,
        gross_quote=gross_quote,
        fee_quote=fee_quote,
        net_quote=net_quote,
        vwap=vwap,
        best_price=best,
        slippage_bps=slippage,
        levels_used=levels_used,
        fully_filled=(remaining_qty <= max(1e-12, quantity * 1e-8)),
    )


def book_microstructure(book: OrderBook, notional_quote: float = 10_000.0) -> dict:
    mid = (book.bids[0].price + book.asks[0].price) / 2.0
    spread_bps = (
        (book.asks[0].price - book.bids[0].price) / mid * 10_000
        if mid > 0
        else 0.0
    )

    buy = buy_with_quote(book, notional_quote)
    sell_qty = notional_quote / book.bids[0].price
    sell = sell_quantity(book, sell_qty)

    bid_depth_quote = sum(level.price * level.quantity for level in book.bids[:10])
    ask_depth_quote = sum(level.price * level.quantity for level in book.asks[:10])
    total_depth = bid_depth_quote + ask_depth_quote
    imbalance = (
        (bid_depth_quote - ask_depth_quote) / total_depth
        if total_depth > 0
        else 0.0
    )

    return {
        "pair": book.pair,
        "best_bid": book.bids[0].price,
        "best_ask": book.asks[0].price,
        "mid": mid,
        "spread_bps": spread_bps,
        "depth_10_bid_usd": bid_depth_quote,
        "depth_10_ask_usd": ask_depth_quote,
        "book_imbalance": imbalance,
        "buy_10k_slippage_bps": buy.slippage_bps,
        "sell_10k_slippage_bps": sell.slippage_bps,
        "taker_fee_bps": DEFAULT_TAKER_FEE_BPS,
    }
