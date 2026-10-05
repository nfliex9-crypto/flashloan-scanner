from __future__ import annotations

import json
import math
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler

from aegis.execution import (
    DEFAULT_TAKER_FEE_BPS,
    buy_with_quote,
    fetch_order_book,
    sell_quantity,
)
from aegis.live_lab import ASSETS


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def parse_float(query: dict, key: str, default: float) -> float:
    try:
        raw = query.get(key, [str(default)])[0]
        value = float(raw)
        if not math.isfinite(value):
            raise ValueError
        return value
    except Exception:
        return default


def simulate_asset(symbol: str, pair: str, notional: float, fee_bps: float) -> dict:
    book = fetch_order_book(pair, 100)
    buy = buy_with_quote(book, notional, fee_bps=fee_bps)
    sell = (
        sell_quantity(book, buy.filled_quantity, fee_bps=fee_bps)
        if buy.filled_quantity > 0
        else None
    )

    best_bid = book.bids[0].price
    best_ask = book.asks[0].price
    mid = (best_bid + best_ask) / 2.0
    spread_bps = ((best_ask - best_bid) / mid * 10_000) if mid > 0 else 0.0

    roundtrip_out = sell.net_quote if sell else 0.0
    roundtrip_pnl = roundtrip_out - notional
    roundtrip_drag_bps = (-roundtrip_pnl / notional * 10_000) if notional > 0 else 0.0

    return {
        "symbol": symbol,
        "pair": pair,
        "notional_usd": notional,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "mid": mid,
        "spread_bps": spread_bps,
        "buy": buy.to_dict(),
        "sell_after_buy": sell.to_dict() if sell else None,
        "roundtrip_out_usd": roundtrip_out,
        "roundtrip_pnl_usd": roundtrip_pnl,
        "roundtrip_drag_bps": roundtrip_drag_bps,
        "base_quantity": buy.filled_quantity,
        "fully_fillable": bool(buy.fully_filled and sell and sell.fully_filled),
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)

        capital = clamp(parse_float(query, "capital", 10_000.0), 100.0, 10_000_000.0)
        risk_pct = clamp(parse_float(query, "risk_pct", 1.0), 0.05, 25.0)
        stop_pct = clamp(parse_float(query, "stop_pct", 2.0), 0.10, 50.0)
        max_position_pct = clamp(parse_float(query, "max_position_pct", 25.0), 1.0, 100.0)
        fee_bps = clamp(parse_float(query, "fee_bps", DEFAULT_TAKER_FEE_BPS), 0.0, 200.0)
        manual_notional = clamp(parse_float(query, "notional", 0.0), 0.0, 10_000_000.0)

        risk_budget = capital * (risk_pct / 100.0)
        stop_fraction = stop_pct / 100.0
        risk_sized_notional = risk_budget / stop_fraction if stop_fraction > 0 else capital
        max_position_usd = capital * (max_position_pct / 100.0)

        suggested_notional = min(capital, max_position_usd, risk_sized_notional)
        notional = manual_notional if manual_notional > 0 else suggested_notional
        notional = clamp(notional, 10.0, capital)

        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = {
                    symbol: pool.submit(simulate_asset, symbol, pair, notional, fee_bps)
                    for symbol, pair in ASSETS.items()
                }
                assets = {symbol: future.result() for symbol, future in futures.items()}

            body = {
                "ok": True,
                "mode": "LIVE_L2_EXECUTION_SANDBOX",
                "capital_firewall": "LOCKED",
                "live_execution_enabled": False,
                "sizing": {
                    "capital_usd": capital,
                    "risk_pct": risk_pct,
                    "stop_pct": stop_pct,
                    "risk_budget_usd": risk_budget,
                    "max_position_pct": max_position_pct,
                    "max_position_usd": max_position_usd,
                    "risk_sized_notional_usd": risk_sized_notional,
                    "manual_notional_usd": manual_notional,
                    "effective_notional_usd": notional,
                    "fee_bps": fee_bps,
                },
                "assets": assets,
                "notes": [
                    "Uses current Kraken L2 snapshot; no real order is sent.",
                    "Risk sizing = risk budget / stop distance, capped by max position and capital.",
                    "Immediate round-trip drag is an execution-cost diagnostic, not a forecast.",
                ],
            }
        except Exception as exc:
            body = {"ok": False, "error": str(exc)[:240], "capital_firewall": "LOCKED"}

        payload = json.dumps(body).encode("utf-8")
        self.send_response(200 if body.get("ok") else 502)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)
