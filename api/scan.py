from __future__ import annotations

import json
from decimal import Decimal
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from scanner import Scanner, USDC, WETH, to_raw


def dec(value: Decimal) -> float:
    return float(value)


def route_to_dict(route, scanner: Scanner, *, include_impact: bool = True) -> dict:
    return {
        "name": route.name,
        "size_usdc": dec(route.start_usdc),
        "end_usdc": dec(route.end_usdc),
        "gross_pnl_usdc": dec(route.gross_pnl_usdc),
        "dex_fee_est_usdc": dec(route.dex_fee_est_usdc),
        "impact_est_pct": dec(route.impact_est_pct) if include_impact else None,
        "gas_est_usdc": dec(route.gas_est_usdc),
        "borrow_fee_est_usdc": dec(route.borrow_fee_est_usdc),
        "net_pnl_usdc": dec(route.net_pnl_usdc),
        "opportunity": route.net_pnl_usdc >= scanner.min_net_profit,
        "buy_fee": route.buy_fee,
        "sell_fee": route.sell_fee,
    }


def market_context(scanner: Scanner):
    block = scanner.w3.eth.block_number
    uni_price, uni_price_quote = scanner.price_weth_in_usdc("uni")
    camelot_price, camelot_price_quote = scanner.price_weth_in_usdc("camelot")
    mid_price = (uni_price + camelot_price) / Decimal(2)
    gas_usdc = scanner.gas_estimate_usdc(mid_price)
    spread = (
        abs(uni_price - camelot_price)
        / min(uni_price, camelot_price)
        * Decimal(100)
    )
    return (
        block,
        uni_price,
        uni_price_quote,
        camelot_price,
        camelot_price_quote,
        mid_price,
        gas_usdc,
        spread,
    )


def build_snapshot(size: Decimal) -> dict:
    scanner = Scanner(trade_size_usdc=size)
    (
        block,
        uni_price,
        uni_price_quote,
        camelot_price,
        camelot_price_quote,
        mid_price,
        gas_usdc,
        spread,
    ) = market_context(scanner)

    routes = [
        scanner.estimate_route("uni", "camelot", mid_price, gas_usdc),
        scanner.estimate_route("camelot", "uni", mid_price, gas_usdc),
    ]
    routes.sort(key=lambda item: item.net_pnl_usdc, reverse=True)

    return {
        "ok": True,
        "mode": "snapshot",
        "network": "Arbitrum One",
        "chain_id": 42161,
        "block": block,
        "trade_size_usdc": dec(size),
        "spread_pct": dec(spread),
        "gas_est_usdc": dec(gas_usdc),
        "flashloan_fee_bps": dec(scanner.borrow_fee_bps),
        "flashloan_fee_pct": dec(scanner.borrow_fee_bps / Decimal(100)),
        "flashloan_fee_source": scanner.borrow_fee_source,
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
        "routes": [route_to_dict(route, scanner) for route in routes],
    }


def build_optimizer() -> dict:
    scanner = Scanner(trade_size_usdc=Decimal("1000"))
    (
        block,
        uni_price,
        uni_price_quote,
        camelot_price,
        camelot_price_quote,
        mid_price,
        gas_usdc,
        spread,
    ) = market_context(scanner)

    # Resolve the best Uniswap fee tier once per direction, then reuse it.
    uni_buy_reference = scanner.quote(
        "uni", USDC, WETH, to_raw(scanner.reference_usdc, 6)
    )
    uni_buy_fee = uni_buy_reference.fee_ppm
    uni_sell_fee = uni_price_quote.fee_ppm

    candidate_sizes = [
        Decimal("100"),
        Decimal("250"),
        Decimal("500"),
        Decimal("1000"),
        Decimal("2500"),
        Decimal("5000"),
        Decimal("10000"),
        Decimal("25000"),
    ]

    candidates = []
    for size in candidate_sizes:
        candidates.append(
            scanner.estimate_route_quick(
                "uni",
                "camelot",
                size,
                mid_price,
                gas_usdc,
                uni_buy_fee_hint=uni_buy_fee,
                uni_sell_fee_hint=uni_sell_fee,
            )
        )
        candidates.append(
            scanner.estimate_route_quick(
                "camelot",
                "uni",
                size,
                mid_price,
                gas_usdc,
                uni_buy_fee_hint=uni_buy_fee,
                uni_sell_fee_hint=uni_sell_fee,
            )
        )

    candidates.sort(key=lambda item: item.net_pnl_usdc, reverse=True)
    best = candidates[0]

    return {
        "ok": True,
        "mode": "optimize",
        "network": "Arbitrum One",
        "chain_id": 42161,
        "block": block,
        "spread_pct": dec(spread),
        "gas_est_usdc": dec(gas_usdc),
        "flashloan_fee_bps": dec(scanner.borrow_fee_bps),
        "flashloan_fee_pct": dec(scanner.borrow_fee_bps / Decimal(100)),
        "flashloan_fee_source": scanner.borrow_fee_source,
        "min_net_profit_usdc": dec(scanner.min_net_profit),
        "best": route_to_dict(best, scanner, include_impact=False),
        "candidates": [
            route_to_dict(route, scanner, include_impact=False)
            for route in candidates[:10]
        ],
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            params = parse_qs(urlparse(self.path).query)
            mode = params.get("mode", ["snapshot"])[0]

            if mode == "optimize":
                body = build_optimizer()
            else:
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
