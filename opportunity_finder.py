from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from web3 import Web3

from scanner import Scanner, USDC, to_raw, from_raw


@dataclass(frozen=True)
class Asset:
    symbol: str
    address: str
    decimals: int


# Liquid Arbitrum assets. Addresses are pinned explicitly so discovery is deterministic.
ASSETS = (
    Asset("WETH", Web3.to_checksum_address("0x82aF49447D8a07e3bd95BD0d56f35241523fBab1"), 18),
    Asset("WBTC", Web3.to_checksum_address("0x2f2a2543B76A4166549F7aaB2e75Bef0aefC5B0f"), 8),
    Asset("ARB", Web3.to_checksum_address("0x912CE59144191C1204E64559FE8253a0e49E6548"), 18),
    Asset("USDT", Web3.to_checksum_address("0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9"), 6),
    Asset("GHO", Web3.to_checksum_address("0x7dfF72693f6A4149b17e7C6314655f6A9F7c8B33"), 18),
    Asset("weETH", Web3.to_checksum_address("0x35751007a407ca6FEFfE80b3cB397736D2cf4dbe"), 18),
)


def dex_name(key: str) -> str:
    return {"uni": "Uniswap V3", "camelot": "Camelot V3"}[key]


def scan_route(
    scanner: Scanner,
    asset: Asset,
    size_usdc: Decimal,
    buy_dex: str,
    sell_dex: str,
    gas_usdc: Decimal,
) -> dict:
    start_raw = to_raw(size_usdc, 6)

    buy = scanner.quote(buy_dex, USDC, asset.address, start_raw)
    token_received = from_raw(buy.amount_out, asset.decimals)

    sell = scanner.quote(sell_dex, asset.address, USDC, buy.amount_out)
    end_usdc = from_raw(sell.amount_out, 6)

    gross = end_usdc - size_usdc
    borrow_fee = size_usdc * scanner.borrow_fee_bps / Decimal(10_000)
    net = gross - borrow_fee - gas_usdc
    edge_pct = gross / size_usdc * Decimal(100)

    return {
        "token": asset.symbol,
        "route": f"{dex_name(buy_dex)} → {dex_name(sell_dex)}",
        "buy_dex": dex_name(buy_dex),
        "sell_dex": dex_name(sell_dex),
        "size_usdc": float(size_usdc),
        "token_received": float(token_received),
        "end_usdc": float(end_usdc),
        "gross_pnl_usdc": float(gross),
        "gross_edge_pct": float(edge_pct),
        "flash_fee_usdc": float(borrow_fee),
        "gas_est_usdc": float(gas_usdc),
        "net_pnl_usdc": float(net),
        "buy_pool_fee": buy.fee_label,
        "sell_pool_fee": sell.fee_label,
        "opportunity": net >= scanner.min_net_profit,
    }


def find_opportunities(size_usdc: Decimal) -> dict:
    scanner = Scanner(trade_size_usdc=size_usdc)

    # Use the live WETH/USDC market only to convert the gas heuristic into USDC.
    uni_weth, _ = scanner.price_weth_in_usdc("uni")
    camelot_weth, _ = scanner.price_weth_in_usdc("camelot")
    weth_mid = (uni_weth + camelot_weth) / Decimal(2)
    gas_usdc = scanner.gas_estimate_usdc(weth_mid)

    results = []
    failures = []

    for asset in ASSETS:
        for buy_dex, sell_dex in (("uni", "camelot"), ("camelot", "uni")):
            try:
                results.append(
                    scan_route(
                        scanner,
                        asset,
                        size_usdc,
                        buy_dex,
                        sell_dex,
                        gas_usdc,
                    )
                )
            except Exception as exc:
                failures.append(
                    {
                        "token": asset.symbol,
                        "route": f"{dex_name(buy_dex)} → {dex_name(sell_dex)}",
                        "error": str(exc)[:220],
                    }
                )

    results.sort(key=lambda item: item["net_pnl_usdc"], reverse=True)

    profitable = [item for item in results if item["opportunity"]]
    positive = [item for item in results if item["net_pnl_usdc"] > 0]

    return {
        "ok": True,
        "mode": "opportunity-radar",
        "network": "Arbitrum One",
        "chain_id": 42161,
        "block": scanner.w3.eth.block_number,
        "trade_size_usdc": float(size_usdc),
        "assets_scanned": len(ASSETS),
        "routes_attempted": len(ASSETS) * 2,
        "routes_quoted": len(results),
        "profitable_count": len(profitable),
        "positive_count": len(positive),
        "min_net_profit_usdc": float(scanner.min_net_profit),
        "flashloan_fee_pct": float(scanner.borrow_fee_bps / Decimal(100)),
        "gas_est_usdc": float(gas_usdc),
        "results": results,
        "failures": failures,
    }
