from __future__ import annotations

import hashlib
import json
import random
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .live_lab import (
    COST_PER_POSITION_CHANGE,
    STRATEGIES,
    TIMEFRAMES,
    annualized_sharpe,
    compounded_return,
    fetch_market_matrix,
    max_drawdown,
    profit_factor,
    strategy_returns,
    trade_count,
)


STATE_PATH = Path("data/evolution_state.json")
STATE_VERSION = 1
CHALLENGERS_PER_FAMILY = 6
PROMOTION_MARGIN = 1.5
STRIKE_LIMIT = 3


@dataclass(frozen=True)
class Genome:
    genome_id: str
    strategy: str
    generation: int
    params: dict[str, float | int]
    parent_id: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _digest_id(strategy: str, generation: int, params: dict) -> str:
    canonical = json.dumps(
        {"strategy": strategy, "generation": generation, "params": params},
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:10]
    return f"{strategy.lower().replace(' ', '-')}-g{generation}-{digest}"


def default_params(strategy: str) -> dict[str, float | int]:
    if strategy == "Trend":
        return {"fast": 18, "slow": 55}
    if strategy == "Momentum":
        return {"lookback": 22, "slow": 60, "min_return": 0.0}
    if strategy == "Mean Reversion":
        return {"lookback": 20, "entry_z": -1.15, "exit_z": -0.05}
    if strategy == "Breakout":
        return {"entry": 24, "exit": 10}
    raise ValueError(f"Unknown strategy: {strategy}")


def default_genome(strategy: str) -> Genome:
    params = default_params(strategy)
    return Genome(
        genome_id=_digest_id(strategy, 0, params),
        strategy=strategy,
        generation=0,
        params=params,
        parent_id=None,
    )


def positions_for_genome(closes: list[float], genome: Genome) -> list[int]:
    strategy = genome.strategy
    p = genome.params
    n = len(closes)
    positions = [0] * n

    if strategy == "Trend":
        fast = int(p["fast"])
        slow = int(p["slow"])
        for i in range(n):
            if i + 1 < slow:
                continue
            fast_mean = sum(closes[i - fast + 1 : i + 1]) / fast
            slow_mean = sum(closes[i - slow + 1 : i + 1]) / slow
            positions[i] = 1 if fast_mean > slow_mean else 0

    elif strategy == "Momentum":
        lookback = int(p["lookback"])
        slow = int(p["slow"])
        min_return = float(p["min_return"])
        for i in range(n):
            if i < lookback or i + 1 < slow:
                continue
            slow_mean = sum(closes[i - slow + 1 : i + 1]) / slow
            momentum = closes[i] / closes[i - lookback] - 1.0
            positions[i] = (
                1
                if momentum > min_return and closes[i] > slow_mean
                else 0
            )

    elif strategy == "Mean Reversion":
        lookback = int(p["lookback"])
        entry_z = float(p["entry_z"])
        exit_z = float(p["exit_z"])
        current = 0

        for i in range(n):
            if i + 1 < lookback:
                continue

            window = closes[i - lookback + 1 : i + 1]
            mean = sum(window) / lookback
            variance = sum((x - mean) ** 2 for x in window) / lookback
            sd = variance**0.5
            z = (closes[i] - mean) / sd if sd > 0 else 0.0

            if z < entry_z:
                current = 1
            elif z > exit_z:
                current = 0

            positions[i] = current

    elif strategy == "Breakout":
        entry = int(p["entry"])
        exit_len = int(p["exit"])
        current = 0

        for i in range(n):
            if i >= entry:
                previous = closes[i - entry : i]
                if closes[i] > max(previous):
                    current = 1

            if i >= exit_len and current:
                previous_exit = closes[i - exit_len : i]
                if closes[i] < min(previous_exit):
                    current = 0

            positions[i] = current

    else:
        raise ValueError(f"Unknown strategy: {strategy}")

    return positions


def _bounded_params(
    strategy: str,
    params: dict[str, float | int],
) -> dict[str, float | int]:
    p = dict(params)

    if strategy == "Trend":
        fast = max(5, min(45, int(round(float(p["fast"])))))
        slow = max(fast + 8, min(180, int(round(float(p["slow"])))))
        return {"fast": fast, "slow": slow}

    if strategy == "Momentum":
        lookback = max(5, min(90, int(round(float(p["lookback"])))))
        slow = max(20, min(180, int(round(float(p["slow"])))))
        min_return = max(-0.02, min(0.03, float(p["min_return"])))
        return {
            "lookback": lookback,
            "slow": slow,
            "min_return": round(min_return, 5),
        }

    if strategy == "Mean Reversion":
        lookback = max(10, min(90, int(round(float(p["lookback"])))))
        entry_z = max(-3.0, min(-0.4, float(p["entry_z"])))
        exit_z = max(-0.6, min(0.8, float(p["exit_z"])))
        if exit_z <= entry_z:
            exit_z = min(0.8, entry_z + 0.5)
        return {
            "lookback": lookback,
            "entry_z": round(entry_z, 3),
            "exit_z": round(exit_z, 3),
        }

    if strategy == "Breakout":
        entry = max(8, min(140, int(round(float(p["entry"])))))
        exit_len = max(4, min(70, int(round(float(p["exit"])))))
        return {"entry": entry, "exit": exit_len}

    raise ValueError(strategy)


def mutate(parent: Genome, *, seed: str) -> Genome:
    raw_seed = hashlib.sha256(
        f"{parent.genome_id}:{seed}".encode("utf-8")
    ).hexdigest()
    rng = random.Random(int(raw_seed[:16], 16))

    p = dict(parent.params)
    strategy = parent.strategy

    if strategy == "Trend":
        p["fast"] = int(p["fast"]) + rng.choice([-4, -3, -2, 2, 3, 4])
        p["slow"] = int(p["slow"]) + rng.choice([-10, -7, -5, 5, 7, 10])

    elif strategy == "Momentum":
        p["lookback"] = int(p["lookback"]) + rng.choice([-8, -5, -3, 3, 5, 8])
        p["slow"] = int(p["slow"]) + rng.choice([-12, -8, -4, 4, 8, 12])
        p["min_return"] = float(p["min_return"]) + rng.choice(
            [-0.004, -0.002, 0.002, 0.004]
        )

    elif strategy == "Mean Reversion":
        p["lookback"] = int(p["lookback"]) + rng.choice([-8, -4, -2, 2, 4, 8])
        p["entry_z"] = float(p["entry_z"]) + rng.choice(
            [-0.25, -0.15, 0.15, 0.25]
        )
        p["exit_z"] = float(p["exit_z"]) + rng.choice(
            [-0.20, -0.10, 0.10, 0.20]
        )

    elif strategy == "Breakout":
        p["entry"] = int(p["entry"]) + rng.choice([-12, -8, -4, 4, 8, 12])
        p["exit"] = int(p["exit"]) + rng.choice([-6, -3, 3, 6])

    p = _bounded_params(strategy, p)
    generation = parent.generation + 1

    return Genome(
        genome_id=_digest_id(strategy, generation, p),
        strategy=strategy,
        generation=generation,
        params=p,
        parent_id=parent.genome_id,
    )


def evaluate_genome(symbol: str, genome: Genome, matrix: dict) -> dict:
    timeframes = {}

    for name, interval in TIMEFRAMES.items():
        candles = matrix[(symbol, name)]
        closes = [c.close for c in candles]
        positions = positions_for_genome(closes, genome)

        returns = strategy_returns(closes, positions)
        split = max(80, int(len(closes) * 0.70))

        oos_closes = closes[split - 1 :]
        oos_positions = positions_for_genome(oos_closes, genome)
        oos_returns = strategy_returns(oos_closes, oos_positions)

        cost2 = strategy_returns(
            closes,
            positions,
            cost_per_change=COST_PER_POSITION_CHANGE * 2,
        )
        cost3 = strategy_returns(
            closes,
            positions,
            cost_per_change=COST_PER_POSITION_CHANGE * 3,
        )

        total = compounded_return(returns)
        oos = compounded_return(oos_returns)
        dd = max_drawdown(returns)
        pf = profit_factor(returns)
        sharpe = annualized_sharpe(returns, interval)
        trades = trade_count(positions)

        stress_passes = sum(
            (
                total > 0,
                oos > 0,
                compounded_return(cost2) > 0,
                compounded_return(cost3) > 0,
            )
        )

        score = 100.0
        score -= min(45.0, dd * 280.0)
        if oos <= 0:
            score -= 20.0
        if pf < 1.15:
            score -= min(20.0, (1.15 - pf) * 35.0)
        if sharpe < 0.5:
            score -= 10.0
        score -= (4 - stress_passes) * 6.0
        if trades < 4:
            score -= 8.0

        timeframes[name] = {
            "return": total,
            "oos_return": oos,
            "max_drawdown": dd,
            "profit_factor": pf,
            "sharpe": sharpe,
            "trades": trades,
            "stress_passes": stress_passes,
            "cost_2x_positive": compounded_return(cost2) > 0,
            "cost_3x_positive": compounded_return(cost3) > 0,
            "score": round(max(0.0, min(100.0, score)), 2),
        }

    weighted_score = round(
        0.25 * timeframes["15m"]["score"]
        + 0.50 * timeframes["1h"]["score"]
        + 0.25 * timeframes["4h"]["score"],
        2,
    )

    confirmations = sum(
        1
        for result in timeframes.values()
        if (
            result["return"] > 0
            and result["oos_return"] > 0
            and result["cost_2x_positive"]
        )
    )

    worst_dd = max(result["max_drawdown"] for result in timeframes.values())
    primary = timeframes["1h"]

    return {
        "symbol": symbol,
        "genome": genome.to_dict(),
        "score": weighted_score,
        "confirmations": confirmations,
        "worst_drawdown": worst_dd,
        "primary_oos_return": primary["oos_return"],
        "primary_profit_factor": primary["profit_factor"],
        "primary_trades": primary["trades"],
        "timeframes": timeframes,
    }


def prosecute(evaluation: dict) -> dict:
    tf = evaluation["timeframes"]
    reasons = []

    checks = {
        "confirmations": evaluation["confirmations"] >= 2,
        "primary_oos": evaluation["primary_oos_return"] > 0,
        "worst_drawdown": evaluation["worst_drawdown"] <= 0.20,
        "cost_2x": sum(1 for x in tf.values() if x["cost_2x_positive"]) >= 2,
        "trade_count": evaluation["primary_trades"] >= 4,
        "score_floor": evaluation["score"] >= 55,
    }

    for name, passed in checks.items():
        if not passed:
            reasons.append(name)

    return {
        "passed": all(checks.values()),
        "checks": checks,
        "failed": reasons,
    }


def should_promote(incumbent: dict, challenger: dict) -> tuple[bool, str]:
    prosecution = prosecute(challenger)
    if not prosecution["passed"]:
        return False, "challenger failed prosecutor gates"

    incumbent_gate = prosecute(incumbent)

    score_gain = challenger["score"] - incumbent["score"]
    dd_limit = max(
        incumbent["worst_drawdown"] + 0.01,
        incumbent["worst_drawdown"] * 1.10,
    )
    risk_ok = challenger["worst_drawdown"] <= dd_limit
    evidence_ok = challenger["confirmations"] >= incumbent["confirmations"]

    if not incumbent_gate["passed"]:
        if challenger["score"] >= 60 and risk_ok:
            return True, "incumbent failed gates and challenger restored robustness"
        return False, "incumbent failed but challenger did not clear rescue threshold"

    if score_gain < PROMOTION_MARGIN:
        return False, f"score gain {score_gain:.2f} < {PROMOTION_MARGIN:.2f}"

    if not risk_ok:
        return False, "challenger improved score by accepting too much drawdown"

    if not evidence_ok:
        return False, "challenger lost cross-timeframe confirmations"

    return True, "challenger improved robustness without weakening risk gates"


def _load_state() -> dict:
    if not STATE_PATH.exists():
        return {
            "version": STATE_VERSION,
            "cycle": 0,
            "last_run_utc": None,
            "incumbents": {},
            "hall_of_fame": [],
            "memory": [],
            "events": [],
        }

    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    if int(state.get("version", 0)) != STATE_VERSION:
        raise RuntimeError("Unsupported evolution-state version")
    return state


def _genome_from_record(record: dict, strategy: str) -> Genome:
    raw = record.get("genome")
    if not raw:
        return default_genome(strategy)

    return Genome(
        genome_id=raw["genome_id"],
        strategy=raw["strategy"],
        generation=int(raw["generation"]),
        params=raw["params"],
        parent_id=raw.get("parent_id"),
    )


def _memory_lesson(
    parent: Genome,
    child: Genome,
    parent_eval: dict,
    child_eval: dict,
    promoted: bool,
) -> dict:
    changed = {
        key: {
            "from": parent.params.get(key),
            "to": child.params.get(key),
        }
        for key in child.params
        if parent.params.get(key) != child.params.get(key)
    }
    return {
        "strategy": parent.strategy,
        "parent": parent.genome_id,
        "child": child.genome_id,
        "changed": changed,
        "score_delta": round(child_eval["score"] - parent_eval["score"], 3),
        "drawdown_delta": round(
            child_eval["worst_drawdown"] - parent_eval["worst_drawdown"],
            6,
        ),
        "promoted": promoted,
    }


def run_cycle() -> dict:
    state = _load_state()
    cycle = int(state.get("cycle", 0)) + 1
    matrix = fetch_market_matrix()

    cycle_events = []
    promotions = []
    rejections = 0

    for symbol in ("BTC", "ETH"):
        for strategy in STRATEGIES:
            family = f"{symbol}:{strategy}"
            current_record = state["incumbents"].get(family, {})
            parent = _genome_from_record(current_record, strategy)
            parent_eval = evaluate_genome(symbol, parent, matrix)

            role_trace = [
                {
                    "role": "HUNTER",
                    "event": "incumbent_loaded",
                    "genome_id": parent.genome_id,
                }
            ]

            challengers = [
                mutate(parent, seed=f"cycle-{cycle}-challenger-{i}")
                for i in range(CHALLENGERS_PER_FAMILY)
            ]

            evaluated = []
            for child in challengers:
                child_eval = evaluate_genome(symbol, child, matrix)
                prosecution = prosecute(child_eval)
                evaluated.append(
                    {
                        "genome": child,
                        "evaluation": child_eval,
                        "prosecution": prosecution,
                    }
                )

            role_trace.append(
                {
                    "role": "PROSECUTOR",
                    "event": "challengers_tested",
                    "tested": len(evaluated),
                    "passed": sum(
                        1 for item in evaluated if item["prosecution"]["passed"]
                    ),
                }
            )

            evaluated.sort(
                key=lambda item: item["evaluation"]["score"],
                reverse=True,
            )
            best = evaluated[0]

            promoted, reason = should_promote(
                parent_eval,
                best["evaluation"],
            )

            strikes = int(current_record.get("strikes", 0))
            if promoted:
                winner = best["genome"]
                winner_eval = best["evaluation"]
                strikes = 0
                promotions.append(
                    {
                        "family": family,
                        "from": parent.genome_id,
                        "to": winner.genome_id,
                        "score_from": parent_eval["score"],
                        "score_to": winner_eval["score"],
                        "reason": reason,
                    }
                )
                role_trace.append(
                    {
                        "role": "JUDGE",
                        "event": "PROMOTE",
                        "winner": winner.genome_id,
                        "reason": reason,
                    }
                )
            else:
                winner = parent
                winner_eval = parent_eval
                rejections += len(evaluated)

                if not prosecute(parent_eval)["passed"]:
                    strikes += 1
                else:
                    strikes = max(0, strikes - 1)

                role_trace.append(
                    {
                        "role": "JUDGE",
                        "event": "KEEP_INCUMBENT",
                        "winner": parent.genome_id,
                        "reason": reason,
                    }
                )

            status = "ACTIVE"
            if strikes >= STRIKE_LIMIT:
                status = "ELIMINATED"
            elif strikes > 0:
                status = "PROBATION"

            state["incumbents"][family] = {
                "family": family,
                "symbol": symbol,
                "strategy": strategy,
                "genome": winner.to_dict(),
                "evaluation": winner_eval,
                "strikes": strikes,
                "status": status,
                "last_cycle": cycle,
            }

            for item in evaluated:
                state["memory"].append(
                    _memory_lesson(
                        parent,
                        item["genome"],
                        parent_eval,
                        item["evaluation"],
                        promoted and item["genome"].genome_id == winner.genome_id,
                    )
                )

            cycle_events.append(
                {
                    "cycle": cycle,
                    "family": family,
                    "status": status,
                    "incumbent_before": parent.genome_id,
                    "incumbent_after": winner.genome_id,
                    "incumbent_score": winner_eval["score"],
                    "strikes": strikes,
                    "role_trace": role_trace,
                    "best_challenger": {
                        "genome": best["genome"].to_dict(),
                        "evaluation": best["evaluation"],
                        "prosecution": best["prosecution"],
                    },
                }
            )

    state["cycle"] = cycle
    state["last_run_utc"] = datetime.now(timezone.utc).isoformat()
    state["events"] = (state.get("events", []) + cycle_events)[-120:]
    state["memory"] = state["memory"][-500:]

    active_records = list(state["incumbents"].values())
    active_records.sort(
        key=lambda record: record["evaluation"]["score"],
        reverse=True,
    )

    state["hall_of_fame"] = [
        {
            "family": record["family"],
            "genome": record["genome"],
            "score": record["evaluation"]["score"],
            "confirmations": record["evaluation"]["confirmations"],
            "worst_drawdown": record["evaluation"]["worst_drawdown"],
            "status": record["status"],
        }
        for record in active_records[:8]
    ]

    state["summary"] = {
        "families": len(state["incumbents"]),
        "promotions_this_cycle": len(promotions),
        "challengers_per_family": CHALLENGERS_PER_FAMILY,
        "challengers_tested": len(state["incumbents"]) * CHALLENGERS_PER_FAMILY,
        "probation": sum(
            1 for record in state["incumbents"].values()
            if record["status"] == "PROBATION"
        ),
        "eliminated": sum(
            1 for record in state["incumbents"].values()
            if record["status"] == "ELIMINATED"
        ),
    }
    state["promotions_this_cycle"] = promotions

    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(state, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return state


def main() -> None:
    state = run_cycle()
    print(
        "AEGIS evolution cycle",
        state["cycle"],
        "promotions=",
        state["summary"]["promotions_this_cycle"],
        "challengers=",
        state["summary"]["challengers_tested"],
    )


if __name__ == "__main__":
    main()
