# Flashloan Scanner — Stage 1

Read-only arbitrage scanner for **Arbitrum One**.

It currently:
- connects to Arbitrum (chain ID 42161)
- reads live WETH/USDC quotes
- compares **Uniswap V3** and **Camelot V3**
- checks both arbitrage directions
- estimates price impact
- estimates DEX fees
- estimates gas heuristically
- calculates estimated net PnL
- prints `OPPORTUNITY` only when estimated net profit is above the configured threshold

It does **not**:
- use a wallet or private key
- send transactions
- borrow funds
- execute swaps
- use real money

## Run in GitHub Codespaces

Open the terminal in your Codespace and run:

```bash
python -m pip install -r requirements.txt
cp .env.example .env
python scanner.py --once
```

For continuous scanning:

```bash
python scanner.py
```

Stop it with `Ctrl+C`.

## Change the simulated trade size

For example, test a 10,000 USDC route:

```bash
python scanner.py --once --size 10000
```

This is only a quote simulation. No funds are used.

## Configuration

Copy the example file:

```bash
cp .env.example .env
```

Important settings:

```env
ARBITRUM_RPC_URL=https://arb1.arbitrum.io/rpc
TRADE_SIZE_USDC=1000
POLL_SECONDS=20
MIN_NET_PROFIT_USDC=1
```

If the public RPC becomes slow or rate-limited, replace `ARBITRUM_RPC_URL`
with your own Arbitrum RPC endpoint.

## How the route calculation works

For each scan the program evaluates both directions:

```text
USDC -> WETH on Uniswap V3 -> USDC on Camelot V3
USDC -> WETH on Camelot V3 -> USDC on Uniswap V3
```

The DEX quoters return an expected output for the requested trade size.
That output already reflects the pool fee and current price impact.

The scanner then subtracts:
- estimated gas
- optional future borrowing fee configured with `BORROW_FEE_BPS`

Stage 1 leaves the borrowing fee at zero because no flash loan is being taken yet.

## Important limitation

The displayed gas value is a heuristic. Arbitrum transaction costs can include
L1 data fees that are not fully represented by a simple `gas_price * gas_units`
calculation.

Before any live execution is added, Stage 2 should use transaction simulation
and a more accurate execution-cost model.

## Safety

Never put a seed phrase or private key in this repository, Codespace, issue,
commit, screenshot, or chat.

The current scanner does not need either one.
