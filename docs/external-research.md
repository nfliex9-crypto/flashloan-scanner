# AEGIS external research inspirations

AEGIS remains a native deterministic research engine. External repositories are
used as architectural references or optional specialists, not blindly copied
into the execution path.

## Kronos — shiyu-coder/Kronos

Use: optional market-forecast specialist.

Why it helps:
- finance-specific OHLCV foundation model rather than a general chat model
- probabilistic forward K-line generation
- open-source mini/small/base models
- MIT licensed

Integration rule:
Kronos forecasts may become one evidence feature. They can never bypass AEGIS
risk gates or directly place an order.

## TradingAgents — TauricResearch/TradingAgents

Use: role decomposition reference.

Useful pattern:
separate analysts, researchers, trader, risk manager, and portfolio manager
instead of asking one agent to do everything.

AEGIS adaptation:
Hunter proposes; Prosecutor attacks; Red Team stress-tests; Judge promotes;
Archivist stores lessons. Deterministic code owns state transitions.

## Microsoft RD-Agent / Qlib

Use: automated quant R&D loop reference.

Useful pattern:
hypothesis -> implementation -> evaluation -> feedback -> next hypothesis.

AEGIS adaptation:
Evolution Lab creates parameterized challengers and only promotes candidates
that improve robustness without weakening drawdown / OOS / cost gates.

## Division Swarm

Use: durable event-state architecture reference.

Useful pattern:
LLMs emit proposals/events, deterministic state machines own routing and state;
replay/fork/audit are first-class.

AEGIS adaptation:
no agent is allowed to self-promote. Promotion is a deterministic Judge rule and
every challenger verdict is persisted to the evolution ledger.

## Agency Swarm / LangGraph Swarm

Use: optional future LLM orchestration layer.

Useful pattern:
specialized roles and controlled handoffs.

AEGIS decision:
do not add the framework dependency yet. The current AEGIS runtime is smaller,
faster, cheaper, and easier to audit. If LLM researchers are added later, they
will sit outside the capital firewall.

## River

Use: future online drift detector.

Useful pattern:
incremental learning and concept-drift detection.

AEGIS plan:
use drift detectors on forward-paper return/error distributions. Drift can demote
an agent automatically, but never promote one by itself.

## Optuna

Use: future challenger search accelerator.

Useful pattern:
parallel hyperparameter search with pruning.

AEGIS plan:
replace part of brute mutation with constrained Optuna trials only after the
evaluation function is stable enough to avoid optimizing bugs.

## Non-negotiable rule

Self-improvement means **measured replacement under immutable risk gates**.
It does not mean allowing an LLM to rewrite risk limits, enable execution, edit
its own evaluator, or promote itself.
