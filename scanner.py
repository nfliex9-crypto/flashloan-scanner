from __future__ import annotations

import argparse
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from web3 import Web3
from web3.exceptions import ContractLogicError

load_dotenv()
console = Console()

CHAIN_ID = 42161
WETH = Web3.to_checksum_address("0x82aF49447D8a07e3bd95BD0d56f35241523fBab1")
USDC = Web3.to_checksum_address("0xaf88d065e77c8cC2239327C5EDb3A432268e5831")

UNISWAP_QUOTER = Web3.to_checksum_address("0xb27308f9F90D607463bb33eA1BeBb41C27CE5AB6")
PANCAKE_QUOTER = Web3.to_checksum_address("0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997")
CAMELOT_QUOTER = Web3.to_checksum_address("0x0Fc73040b26E9bC8514fA028D998E73A254Fa76E")
AAVE_POOL = Web3.to_checksum_address("0x794a61358D6845594F94dc1DB02A252b5b4814aD")

UNISWAP_QUOTER_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "tokenIn", "type": "address"},
            {"internalType": "address", "name": "tokenOut", "type": "address"},
            {"internalType": "uint24", "name": "fee", "type": "uint24"},
            {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
            {"internalType": "uint160", "name": "sqrtPriceLimitX96", "type": "uint160"},
        ],
        "name": "quoteExactInputSingle",
        "outputs": [{"internalType": "uint256", "name": "amountOut", "type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function",
    }
]


PANCAKE_QUOTER_ABI = [
    {
        "inputs": [
            {
                "components": [
                    {"internalType": "address", "name": "tokenIn", "type": "address"},
                    {"internalType": "address", "name": "tokenOut", "type": "address"},
                    {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                    {"internalType": "uint24", "name": "fee", "type": "uint24"},
                    {"internalType": "uint160", "name": "sqrtPriceLimitX96", "type": "uint160"},
                ],
                "internalType": "struct IQuoterV2.QuoteExactInputSingleParams",
                "name": "params",
                "type": "tuple",
            }
        ],
        "name": "quoteExactInputSingle",
        "outputs": [
            {"internalType": "uint256", "name": "amountOut", "type": "uint256"},
            {"internalType": "uint160", "name": "sqrtPriceX96After", "type": "uint160"},
            {"internalType": "uint32", "name": "initializedTicksCrossed", "type": "uint32"},
            {"internalType": "uint256", "name": "gasEstimate", "type": "uint256"},
        ],
        "stateMutability": "nonpayable",
        "type": "function",
    }
]

CAMELOT_QUOTER_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "tokenIn", "type": "address"},
            {"internalType": "address", "name": "tokenOut", "type": "address"},
            {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
            {"internalType": "uint160", "name": "limitSqrtPrice", "type": "uint160"},
        ],
        "name": "quoteExactInputSingle",
        "outputs": [
            {"internalType": "uint256", "name": "amountOut", "type": "uint256"},
            {"internalType": "uint16", "name": "fee", "type": "uint16"},
        ],
        "stateMutability": "nonpayable",
        "type": "function",
    }
]

AAVE_POOL_ABI = [
    {
        "inputs": [],
        "name": "FLASHLOAN_PREMIUM_TOTAL",
        "outputs": [{"internalType": "uint128", "name": "", "type": "uint128"}],
        "stateMutability": "view",
        "type": "function",
    }
]


def env_decimal(name: str, default: str) -> Decimal:
    raw = os.getenv(name, default)
    try:
        return Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"{name} must be a number, got: {raw}") from exc


def env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def parse_fee_tiers(value: str) -> tuple[int, ...]:
    tiers = tuple(int(part.strip()) for part in value.split(",") if part.strip())
    if not tiers:
        raise ValueError("UNISWAP_FEE_TIERS cannot be empty")
    return tiers


def to_raw(amount: Decimal, decimals: int) -> int:
    return int(amount * (Decimal(10) ** decimals))


def from_raw(amount: int, decimals: int) -> Decimal:
    return Decimal(amount) / (Decimal(10) ** decimals)


@dataclass(frozen=True)
class Quote:
    dex: str
    amount_in: int
    amount_out: int
    fee_ppm: int
    fee_label: str


@dataclass(frozen=True)
class RouteResult:
    name: str
    start_usdc: Decimal
    end_usdc: Decimal
    gross_pnl_usdc: Decimal
    dex_fee_est_usdc: Decimal
    impact_est_pct: Decimal
    gas_est_usdc: Decimal
    borrow_fee_est_usdc: Decimal
    net_pnl_usdc: Decimal
    buy_fee: str
    sell_fee: str


class Scanner:
    def __init__(self, trade_size_usdc: Decimal) -> None:
        self.rpc_url = os.getenv("ARBITRUM_RPC_URL", "https://arb1.arbitrum.io/rpc")
        request_kwargs = {"timeout": env_int("RPC_TIMEOUT_SECONDS", 15)}
        self.w3 = Web3(Web3.HTTPProvider(self.rpc_url, request_kwargs=request_kwargs))

        if not self.w3.is_connected():
            raise RuntimeError("Could not connect to Arbitrum RPC.")
        if self.w3.eth.chain_id != CHAIN_ID:
            raise RuntimeError(
                f"Wrong network: expected chain ID {CHAIN_ID}, got {self.w3.eth.chain_id}."
            )

        self.trade_size_usdc = trade_size_usdc
        self.reference_usdc = env_decimal("REFERENCE_USDC", "10")
        self.reference_weth = env_decimal("REFERENCE_WETH", "0.01")
        self.min_net_profit = env_decimal("MIN_NET_PROFIT_USDC", "1")
        self.gas_units = env_int("GAS_UNITS_ESTIMATE", 850000)
        self.gas_buffer = env_decimal("GAS_BUFFER_MULTIPLIER", "1.20")
        self.uniswap_fee_tiers = parse_fee_tiers(
            os.getenv("UNISWAP_FEE_TIERS", "100,500,3000,10000")
        )
        self.pancake_fee_tiers = parse_fee_tiers(
            os.getenv("PANCAKE_FEE_TIERS", "100,500,2500,10000")
        )

        self.uni = self.w3.eth.contract(
            address=UNISWAP_QUOTER, abi=UNISWAP_QUOTER_ABI
        )
        self.pancake = self.w3.eth.contract(
            address=PANCAKE_QUOTER, abi=PANCAKE_QUOTER_ABI
        )
        self.camelot = self.w3.eth.contract(
            address=CAMELOT_QUOTER, abi=CAMELOT_QUOTER_ABI
        )
        self.aave_pool = self.w3.eth.contract(
            address=AAVE_POOL, abi=AAVE_POOL_ABI
        )

        borrow_override = os.getenv("BORROW_FEE_BPS", "").strip()
        if borrow_override:
            self.borrow_fee_bps = Decimal(borrow_override)
            self.borrow_fee_source = "env-override"
        else:
            self.borrow_fee_bps = Decimal(
                self.aave_pool.functions.FLASHLOAN_PREMIUM_TOTAL().call()
            )
            self.borrow_fee_source = "aave-live"

    def quote_uniswap(
        self, token_in: str, token_out: str, amount_in: int, fee_hint: int | None = None
    ) -> Quote:
        tiers = (fee_hint,) if fee_hint is not None else self.uniswap_fee_tiers
        best: Quote | None = None
        last_error: Exception | None = None

        for fee in tiers:
            try:
                amount_out = self.uni.functions.quoteExactInputSingle(
                    token_in, token_out, fee, amount_in, 0
                ).call()
                quote = Quote(
                    dex="Uniswap V3",
                    amount_in=amount_in,
                    amount_out=int(amount_out),
                    fee_ppm=fee,
                    fee_label=f"{Decimal(fee) / Decimal(10000):.4f}%",
                )
                if best is None or quote.amount_out > best.amount_out:
                    best = quote
            except Exception as exc:
                last_error = exc

        if best is None:
            detail = f" ({last_error})" if last_error else ""
            raise RuntimeError(f"No usable Uniswap V3 quote{detail}")
        return best


    def quote_pancake(
        self, token_in: str, token_out: str, amount_in: int, fee_hint: int | None = None
    ) -> Quote:
        tiers = (fee_hint,) if fee_hint is not None else self.pancake_fee_tiers
        best: Quote | None = None
        last_error: Exception | None = None

        for fee in tiers:
            try:
                result = self.pancake.functions.quoteExactInputSingle(
                    (token_in, token_out, amount_in, fee, 0)
                ).call()
                quote = Quote(
                    dex="PancakeSwap V3",
                    amount_in=amount_in,
                    amount_out=int(result[0]),
                    fee_ppm=fee,
                    fee_label=f"{Decimal(fee) / Decimal(10000):.4f}%",
                )
                if best is None or quote.amount_out > best.amount_out:
                    best = quote
            except Exception as exc:
                last_error = exc

        if best is None:
            detail = f" ({last_error})" if last_error else ""
            raise RuntimeError(f"No usable PancakeSwap V3 quote{detail}")
        return best

    def quote_camelot(self, token_in: str, token_out: str, amount_in: int) -> Quote:
        try:
            result = self.camelot.functions.quoteExactInputSingle(
                token_in, token_out, amount_in, 0
            ).call()
            amount_out, fee_ppm = int(result[0]), int(result[1])
        except (ContractLogicError, ValueError, OSError) as exc:
            raise RuntimeError(f"Camelot V3 quote failed: {exc}") from exc
        except Exception as exc:
            raise RuntimeError(f"Camelot V3 quote failed: {exc}") from exc

        return Quote(
            dex="Camelot V3",
            amount_in=amount_in,
            amount_out=amount_out,
            fee_ppm=fee_ppm,
            fee_label=f"{Decimal(fee_ppm) / Decimal(10000):.4f}%",
        )

    def quote(
        self,
        dex: str,
        token_in: str,
        token_out: str,
        amount_in: int,
        fee_hint: int | None = None,
    ) -> Quote:
        if dex == "uni":
            return self.quote_uniswap(token_in, token_out, amount_in, fee_hint)
        if dex == "pancake":
            return self.quote_pancake(token_in, token_out, amount_in, fee_hint)
        if dex == "camelot":
            return self.quote_camelot(token_in, token_out, amount_in)
        raise ValueError(f"Unknown DEX: {dex}")

    def reference_quote(
        self,
        dex: str,
        token_in: str,
        token_out: str,
        amount_in: int,
        main_quote: Quote,
    ) -> Quote:
        fee_hint = main_quote.fee_ppm if dex in ("uni", "pancake") else None
        return self.quote(dex, token_in, token_out, amount_in, fee_hint)

    def price_weth_in_usdc(self, dex: str) -> tuple[Decimal, Quote]:
        amount_in = to_raw(self.reference_weth, 18)
        quote = self.quote(dex, WETH, USDC, amount_in)
        price = from_raw(quote.amount_out, 6) / self.reference_weth
        return price, quote

    def estimate_route(
        self,
        buy_dex: str,
        sell_dex: str,
        weth_usdc_reference_price: Decimal,
        gas_est_usdc: Decimal,
    ) -> RouteResult:
        start_raw = to_raw(self.trade_size_usdc, 6)

        buy = self.quote(buy_dex, USDC, WETH, start_raw)
        weth_received = from_raw(buy.amount_out, 18)

        buy_ref = self.reference_quote(
            buy_dex,
            USDC,
            WETH,
            to_raw(self.reference_usdc, 6),
            buy,
        )
        buy_rate = weth_received / self.trade_size_usdc
        buy_ref_rate = from_raw(buy_ref.amount_out, 18) / self.reference_usdc
        buy_impact = (
            max(Decimal(0), (buy_ref_rate - buy_rate) / buy_ref_rate * 100)
            if buy_ref_rate > 0
            else Decimal(0)
        )

        sell = self.quote(sell_dex, WETH, USDC, buy.amount_out)
        end_usdc = from_raw(sell.amount_out, 6)

        sell_ref = self.reference_quote(
            sell_dex,
            WETH,
            USDC,
            to_raw(self.reference_weth, 18),
            sell,
        )
        sell_rate = end_usdc / weth_received if weth_received > 0 else Decimal(0)
        sell_ref_rate = from_raw(sell_ref.amount_out, 6) / self.reference_weth
        sell_impact = (
            max(Decimal(0), (sell_ref_rate - sell_rate) / sell_ref_rate * 100)
            if sell_ref_rate > 0
            else Decimal(0)
        )

        # Informational only. Quoter output already includes pool fee + price impact.
        buy_fee_usdc = self.trade_size_usdc * Decimal(buy.fee_ppm) / Decimal(1_000_000)
        sell_fee_weth = weth_received * Decimal(sell.fee_ppm) / Decimal(1_000_000)
        sell_fee_usdc = sell_fee_weth * weth_usdc_reference_price
        dex_fee_est = buy_fee_usdc + sell_fee_usdc

        gross_pnl = end_usdc - self.trade_size_usdc
        borrow_fee = self.trade_size_usdc * self.borrow_fee_bps / Decimal(10_000)
        net_pnl = gross_pnl - gas_est_usdc - borrow_fee

        return RouteResult(
            name=f"{buy.dex} → {sell.dex}",
            start_usdc=self.trade_size_usdc,
            end_usdc=end_usdc,
            gross_pnl_usdc=gross_pnl,
            dex_fee_est_usdc=dex_fee_est,
            impact_est_pct=buy_impact + sell_impact,
            gas_est_usdc=gas_est_usdc,
            borrow_fee_est_usdc=borrow_fee,
            net_pnl_usdc=net_pnl,
            buy_fee=buy.fee_label,
            sell_fee=sell.fee_label,
        )


    def estimate_route_quick(
        self,
        buy_dex: str,
        sell_dex: str,
        size_usdc: Decimal,
        weth_usdc_reference_price: Decimal,
        gas_est_usdc: Decimal,
        uni_buy_fee_hint: int | None = None,
        uni_sell_fee_hint: int | None = None,
    ) -> RouteResult:
        start_raw = to_raw(size_usdc, 6)

        buy_hint = uni_buy_fee_hint if buy_dex == "uni" else None
        sell_hint = uni_sell_fee_hint if sell_dex == "uni" else None

        buy = self.quote(buy_dex, USDC, WETH, start_raw, buy_hint)
        weth_received = from_raw(buy.amount_out, 18)
        sell = self.quote(sell_dex, WETH, USDC, buy.amount_out, sell_hint)
        end_usdc = from_raw(sell.amount_out, 6)

        buy_fee_usdc = size_usdc * Decimal(buy.fee_ppm) / Decimal(1_000_000)
        sell_fee_weth = weth_received * Decimal(sell.fee_ppm) / Decimal(1_000_000)
        sell_fee_usdc = sell_fee_weth * weth_usdc_reference_price
        dex_fee_est = buy_fee_usdc + sell_fee_usdc

        gross_pnl = end_usdc - size_usdc
        borrow_fee = size_usdc * self.borrow_fee_bps / Decimal(10_000)
        net_pnl = gross_pnl - gas_est_usdc - borrow_fee

        return RouteResult(
            name=f"{buy.dex} → {sell.dex}",
            start_usdc=size_usdc,
            end_usdc=end_usdc,
            gross_pnl_usdc=gross_pnl,
            dex_fee_est_usdc=dex_fee_est,
            impact_est_pct=Decimal("0"),
            gas_est_usdc=gas_est_usdc,
            borrow_fee_est_usdc=borrow_fee,
            net_pnl_usdc=net_pnl,
            buy_fee=buy.fee_label,
            sell_fee=sell.fee_label,
        )

    def gas_estimate_usdc(self, weth_price_usdc: Decimal) -> Decimal:
        gas_price_wei = Decimal(self.w3.eth.gas_price)
        gas_eth = (
            gas_price_wei
            * Decimal(self.gas_units)
            * self.gas_buffer
            / Decimal(10**18)
        )
        return gas_eth * weth_price_usdc

    def snapshot(self) -> tuple[int, Decimal, Decimal, list[RouteResult]]:
        block = self.w3.eth.block_number
        uni_price, uni_price_quote = self.price_weth_in_usdc("uni")
        camelot_price, camelot_price_quote = self.price_weth_in_usdc("camelot")

        mid_price = (uni_price + camelot_price) / Decimal(2)
        gas_usdc = self.gas_estimate_usdc(mid_price)

        route_uni_to_camelot = self.estimate_route(
            "uni", "camelot", mid_price, gas_usdc
        )
        route_camelot_to_uni = self.estimate_route(
            "camelot", "uni", mid_price, gas_usdc
        )

        spread = (
            abs(uni_price - camelot_price)
            / min(uni_price, camelot_price)
            * Decimal(100)
        )

        self.render(
            block,
            uni_price,
            camelot_price,
            spread,
            uni_price_quote,
            camelot_price_quote,
            gas_usdc,
            [route_uni_to_camelot, route_camelot_to_uni],
        )
        return block, uni_price, camelot_price, [
            route_uni_to_camelot,
            route_camelot_to_uni,
        ]

    def render(
        self,
        block: int,
        uni_price: Decimal,
        camelot_price: Decimal,
        spread_pct: Decimal,
        uni_price_quote: Quote,
        camelot_price_quote: Quote,
        gas_usdc: Decimal,
        routes: list[RouteResult],
    ) -> None:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        console.rule(f"[bold cyan]Arbitrum WETH/USDC Scanner[/bold cyan]  {now}")
        console.print(
            f"Block [bold]{block}[/bold] • Size [bold]USD {self.trade_size_usdc:,.2f}[/bold] "
            f"• Spread [bold]{spread_pct:.4f}%[/bold] • Gas heuristic [bold]USD {gas_usdc:.4f}[/bold]"
        )

        prices = Table(show_header=True, header_style="bold")
        prices.add_column("DEX")
        prices.add_column("WETH → USDC", justify="right")
        prices.add_column("Fee", justify="right")
        prices.add_row("Uniswap V3", f"USD {uni_price:,.4f}", uni_price_quote.fee_label)
        prices.add_row("Camelot V3", f"USD {camelot_price:,.4f}", camelot_price_quote.fee_label)
        console.print(prices)

        routes_table = Table(show_header=True, header_style="bold")
        routes_table.add_column("Route")
        routes_table.add_column("End USDC", justify="right")
        routes_table.add_column("Gross PnL*", justify="right")
        routes_table.add_column("DEX fee est.", justify="right")
        routes_table.add_column("Impact est.", justify="right")
        routes_table.add_column("Gas est.", justify="right")
        routes_table.add_column("Borrow fee", justify="right")
        routes_table.add_column("Net est.", justify="right")
        routes_table.add_column("Decision")

        for route in sorted(routes, key=lambda item: item.net_pnl_usdc, reverse=True):
            decision = (
                "[bold green]OPPORTUNITY[/bold green]"
                if route.net_pnl_usdc >= self.min_net_profit
                else "[dim]NO TRADE[/dim]"
            )
            routes_table.add_row(
                route.name,
                f"USD {route.end_usdc:,.4f}",
                f"USD {route.gross_pnl_usdc:,.4f}",
                f"USD {route.dex_fee_est_usdc:,.4f}",
                f"{route.impact_est_pct:.4f}%",
                f"USD {route.gas_est_usdc:,.4f}",
                f"USD {route.borrow_fee_est_usdc:,.4f}",
                f"USD {route.net_pnl_usdc:,.4f}",
                decision,
            )
        console.print(routes_table)
        console.print(
            "[dim]* Gross PnL comes from real on-chain quoter output and already includes "
            "DEX pool fees + price impact. Fee/impact columns are diagnostics, not extra deductions. "
            "Gas is a heuristic; Arbitrum L1 data costs can make real execution more expensive.[/dim]"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only WETH/USDC arbitrage scanner for Arbitrum."
    )
    parser.add_argument("--once", action="store_true", help="Run one scan and exit.")
    parser.add_argument(
        "--size",
        type=Decimal,
        default=env_decimal("TRADE_SIZE_USDC", "1000"),
        help="Starting USDC notional used for route quotes.",
    )
    args = parser.parse_args()

    scanner = Scanner(trade_size_usdc=args.size)
    poll_seconds = env_int("POLL_SECONDS", 20)

    console.print(
        "[bold green]Read-only mode.[/bold green] No wallet, private key, borrowing, or transactions."
    )

    while True:
        try:
            scanner.snapshot()
        except KeyboardInterrupt:
            console.print("\nStopped.")
            return
        except Exception as exc:
            console.print(f"[bold red]Scan error:[/bold red] {exc}")

        if args.once:
            return

        try:
            time.sleep(poll_seconds)
        except KeyboardInterrupt:
            console.print("\nStopped.")
            return


if __name__ == "__main__":
    main()
