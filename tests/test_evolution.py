from aegis.evolution import (
    Genome,
    default_genome,
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
