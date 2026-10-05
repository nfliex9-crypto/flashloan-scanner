from aegis.evolution import (
    Genome,
    default_genome,
    learned_parameter_votes,
    memory_aware_challenger,
    mutate,
    positions_for_genome,
    prosecute,
    should_promote,
)


def test_mutation_is_deterministic_and_changes_genome():
    parent = default_genome("Trend")
    a = mutate(parent, seed="same")
    b = mutate(parent, seed="same")
    assert a == b
    assert a.genome_id != parent.genome_id
    assert a.parent_id == parent.genome_id


def test_positions_support_all_strategy_families():
    closes = [100 + i * 0.2 + ((i % 7) - 3) * 0.1 for i in range(250)]
    for name in ("Trend", "Momentum", "Mean Reversion", "Breakout"):
        genome = default_genome(name)
        positions = positions_for_genome(closes, genome)
        assert len(positions) == len(closes)
        assert set(positions).issubset({0, 1})


def evaluation(score=70, dd=0.08, confirmations=2, oos=0.03, trades=10):
    tf = {
        "15m": {
            "cost_2x_positive": True,
        },
        "1h": {
            "cost_2x_positive": True,
        },
        "4h": {
            "cost_2x_positive": False,
        },
    }
    return {
        "score": score,
        "worst_drawdown": dd,
        "confirmations": confirmations,
        "primary_oos_return": oos,
        "primary_trades": trades,
        "timeframes": tf,
    }


def test_prosecutor_requires_robust_evidence():
    passed = prosecute(evaluation())
    failed = prosecute(evaluation(oos=-0.01))
    assert passed["passed"] is True
    assert failed["passed"] is False
    assert "primary_oos" in failed["failed"]


def test_judge_rejects_profit_improvement_with_excess_drawdown():
    incumbent = evaluation(score=70, dd=0.06)
    reckless = evaluation(score=80, dd=0.15)
    promote, reason = should_promote(incumbent, reckless)
    assert promote is False
    assert "drawdown" in reason


def test_judge_can_promote_stronger_challenger():
    incumbent = evaluation(score=70, dd=0.08)
    challenger = evaluation(score=74, dd=0.075)
    promote, _ = should_promote(incumbent, challenger)
    assert promote is True


def test_memory_votes_learn_only_from_safe_improvements():
    memory = [
        {
            "strategy": "Trend",
            "changed": {"fast": {"from": 18, "to": 22}},
            "score_delta": 4.0,
            "drawdown_delta": -0.01,
            "promoted": True,
        },
        {
            "strategy": "Trend",
            "changed": {"fast": {"from": 18, "to": 14}},
            "score_delta": 1.0,
            "drawdown_delta": 0.05,
            "promoted": False,
        },
    ]
    votes = learned_parameter_votes(memory, "Trend")
    assert votes["fast"] > 0


def test_memory_aware_challenger_preserves_risk_gate_separation():
    parent = default_genome("Trend")
    memory = [
        {
            "strategy": "Trend",
            "changed": {"fast": {"from": 18, "to": 22}},
            "score_delta": 3.0,
            "drawdown_delta": 0.0,
            "promoted": True,
        }
    ]
    child = memory_aware_challenger(parent, memory, seed="memory-test")
    assert child.generation == parent.generation + 1
    assert child.parent_id == parent.genome_id
    assert set(child.params) == set(parent.params)
