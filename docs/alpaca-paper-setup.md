# Connect AEGIS to a real Alpaca Paper account

AEGIS supports an **actual Alpaca Paper Trading account**. It never uses the
Alpaca live-money domain.

Hard-coded broker endpoint:

```text
https://paper-api.alpaca.markets
```

## What you need

Create an Alpaca Paper Only account and generate its **paper** API key + secret.

Do not use a live-account key.

## Vercel environment variables

Add these to the `flashloan-scanner` project, Production environment:

```text
ALPACA_PAPER_API_KEY=<paper key id>
ALPACA_PAPER_API_SECRET=<paper secret>
AEGIS_CONTROL_TOKEN=<a long random password only you know>
AEGIS_PAPER_MAX_ORDER_USD=1000
```

The dashboard will then show the actual paper account balance, positions, and
orders. Manual paper orders require the control token.

## GitHub Actions secrets

For scheduled Auto-Paper, add repository secrets:

```text
ALPACA_PAPER_API_KEY
ALPACA_PAPER_API_SECRET
```

Then add repository variables:

```text
AEGIS_AUTOPAPER_ENABLED=1
AEGIS_BASE_RISK_PCT=0.50
AEGIS_STOP_PCT=2.0
AEGIS_MAX_POSITION_PCT=10
AEGIS_PAPER_MAX_ORDER_USD=1000
```

Leave `AEGIS_AUTOPAPER_ENABLED` unset or `0` until you explicitly want the
scheduled paper runner to submit simulated orders.

## Safety architecture

- Alpaca URL is hard-coded to the paper API.
- The brain can only reduce risk through a multiplier from 0 to 1.
- The brain cannot raise base risk.
- The brain cannot edit risk gates.
- The public dashboard cannot read the account without `AEGIS_CONTROL_TOKEN`.
- Manual orders are capped by `AEGIS_PAPER_MAX_ORDER_USD`.
- Auto-Paper is disabled by default.
- Real-money trading is not implemented in this adapter.
