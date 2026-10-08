# AEGIS — Zero-Trust Quant Lab

AEGIS is a personal research system built around one rule:

> A strategy is guilty until it survives attempts to falsify it.

This is not a signal bot and it does not promise loss-free trading. It is an adversarial
research and capital-gating engine. AI may propose and critique ideas, but deterministic
statistical/risk gates decide whether a strategy can progress.

## Core design

1. **Hunter** — generates transparent candidate strategies.
2. **Prosecutor** — penalizes multiple testing / overfitting.
3. **Market Forge** — creates counterfactual stress scenarios.
4. **Red Team** — searches for failure modes rather than profit.
5. **Evidence Ledger** — hashes every evaluation so results cannot be quietly rewritten.
6. **Capital Firewall** — no strategy can reach capital unless all hard gates pass.
7. **Drift Watch** — compares forward behavior with the distribution promised by research.

The first milestone is research + shadow/paper mode only. No wallet, broker API,
private key, or automatic live execution is enabled.

## Survival-first objective

AEGIS does **not** optimize raw return first. It ranks candidates by a Survival Score
built from drawdown, probability of backtest overfitting, cost survival, regime stability,
parameter stability, forward evidence, and probability-of-ruin estimates.

A spectacular backtest can score lower than a modest but stable system.

## Initial hard gates

These are research defaults, not claims that a passing strategy is safe:

- at least 200 historical trades
- max drawdown <= 10%
- profit factor >= 1.25
- Deflated Sharpe confidence >= 0.95
- Probability of Backtest Overfitting <= 20%
- survives at least 2x assumed trading costs
- parameter-neighborhood stability >= 70%
- regime pass rate >= 70%
- paper evidence >= 30 days before canary eligibility
- estimated probability of ruin <= 1%

The thresholds are versioned and every verdict is recorded.

## Run the demo

```bash
pip install -r requirements-aegis.txt
python -m aegis.demo
pytest -q tests/test_aegis.py
```

The demo contains no market connection and places no orders.


## Continuous bounded Shadow Research — Agent City

The `agent-city-v1` research lab evaluates **EMA Cross**, **RSI Pullback**, and
**Channel Breakout** for BTC/USD and XAU/USD on genuine closed hourly bars.
Each candidate receives its own independent costed **shadow-only** account;
no candidate gets main paper account allocation, broker order access, or live money.
Strategies are reviewed on historical out-of-sample slices, but only *future*
persisted costed shadow fills count toward forward ranking and quarantine.
This is evidence-based adaptation, **not continuous ML-model retraining**.

Neon migration: `sql/004_research_controls.sql` (additive, idempotent).
Default settings: enabled, BTC + XAU, three strategies, six total candidates.
The hourly engine reads these settings and the 15-minute monitor records the
configuration. Historical trade records are never fabricated.

**Authenticated owner control:** In Vercel project settings on the
`agent-city-v1` Preview environment, create a Sensitive environment variable
named `AEGIS_CONTROL_TOKEN` containing an independent, randomly generated
secret **at least 24 characters long**. Redeploy the Preview branch and paste
that secret into the **Research Lab → Owner Control Key** field to save settings.
The browser does not put this secret in URLs, localStorage, or cookies, and
clears the field after each save. Do not use an OANDA, Alpaca, Twelve Data,
database, or scheduler credential as this control token.

The owner can pause new research experiments, choose BTC/XAU, enable/disable
the three candidate families, and set a cap of 2/4/6 candidates.
Existing virtual positions remain subject to exits even when experimentation
is paused. There is **no live-broker or order-control route**.
