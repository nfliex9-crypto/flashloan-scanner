from __future__ import annotations

import json
from decimal import Decimal
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from scanner import Scanner


def dec(value: Decimal) -> float:
    return float(value)


def build_snapshot(size: Decimal) -> dict:
    scanner = Scanner(trade_size_usdc=size)

    block = scanner.w3.eth.block_number
    uni_price, uni_price_quote = scanner.price_weth_in_usdc("uni")
    camelot_price, camelot_price_quote = scanner.price_weth_in_usdc("camelot")

    mid_price = (uni_price + camelot_price) / Decimal(2)
    gas_usdc = scanner.gas_estimate_usdc(mid_price)

    routes = [
        scanner.estimate_route("uni", "camelot", mid_price, gas_usdc),
        scanner.estimate_route("camelot", "uni", mid_price, gas_usdc),
    ]
    routes.sort(key=lambda item: item.net_pnl_usdc, reverse=True)

    spread = (
        abs(uni_price - camelot_price)
        / min(uni_price, camelot_price)
        * Decimal(100)
    )

    return {
        "ok": True,
        "network": "Arbitrum One",
        "chain_id": 42161,
        "block": block,
        "trade_size_usdc": dec(size),
        "spread_pct": dec(spread),
        "gas_est_usdc": dec(gas_usdc),
        "min_net_profit_usdc": dec(scanner.min_net_profit),
        "prices": [
            {
                "dex": "Uniswap V3",
                "weth_usdc": dec(uni_price),
                "fee": uni_price_quote.fee_label,
            },
            {
                "dex": "Camelot V3",
                "weth_usdc": dec(camelot_price),
                "fee": camelot_price_quote.fee_label,
            },
        ],
        "routes": [
            {
                "name": route.name,
                "end_usdc": dec(route.end_usdc),
                "gross_pnl_usdc": dec(route.gross_pnl_usdc),
                "dex_fee_est_usdc": dec(route.dex_fee_est_usdc),
                "impact_est_pct": dec(route.impact_est_pct),
                "gas_est_usdc": dec(route.gas_est_usdc),
                "borrow_fee_est_usdc": dec(route.borrow_fee_est_usdc),
                "net_pnl_usdc": dec(route.net_pnl_usdc),
                "opportunity": route.net_pnl_usdc >= scanner.min_net_profit,
                "buy_fee": route.buy_fee,
                "sell_fee": route.sell_fee,
            }
            for route in routes
        ],
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            params = parse_qs(urlparse(self.path).query)
            raw_size = params.get("size", ["1000"])[0]
            size = Decimal(raw_size)
            if size <= 0 or size > Decimal("10000000"):
                raise ValueError("size must be between 0 and 10,000,000 USDC")

            body = build_snapshot(size)
            status = 200
        except Exception as exc:
            body = {"ok": False, "error": str(exc)}
            status = 500

        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)
