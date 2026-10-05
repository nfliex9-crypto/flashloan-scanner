from aegis.arena import (
    AgentGenome,
    AgentScore,
    AgentState,
    AgentStatus,
    SurvivalArena,
    rank_population,
)
from aegis.protocol import pressure_context


def state():
    return AgentState(
        genome=AgentGenome(
            agent_id="hunter-01-g0",
            generation=0,
            risk_aversion=0.7,
            exploration_rate=0.2,
            regime_sensitivity=0.7,
            cost_sensitivity=0.8,
        )
    )


def score(**overrides):
    data = dict(
        target_return=0.03,
        realized_return=0.035,
        max_drawdown=0.05,
        max_allowed_drawdown=0.08,
        rule_violations=0,
        falsification_failures=0,
        paper_days=30,
    )
    data.update(overrides)
    return AgentScore(**data)


def test_good_episode_keeps_agent_active():
    s = state()
    d = SurvivalArena().evaluate(s, score())
    assert d.status is AgentStatus.ACTIVE
    assert d.action == "KEEP_ACTIVE"
    assert d.strikes == 0


def test_repeated_failure_eliminates_and_spawns_successor():
    s = state()
    arena = SurvivalArena(strike_limit=3)

    d = None
    for _ in range(3):
        d = arena.evaluate(
            s,
            score(
                realized_return=0.005,
                falsification_failures=2,
            ),
        )

    assert d is not None
    assert d.status is AgentStatus.ELIMINATED
    assert d.action == "ELIMINATE_AND_REPLACE"
    assert d.replacement is not None
    assert d.replacement.generation == 1
    assert d.replacement.agent_id.endswith("-g1")


def test_two_hard_rule_violations_cause_immediate_elimination():
    s = state()
    d = SurvivalArena().evaluate(
        s,
        score(rule_violations=2),
    )
    assert d.status is AgentStatus.ELIMINATED
    assert d.replacement is not None


def test_risk_breach_is_worse_than_simple_target_miss():
    arena = SurvivalArena()

    target_miss = arena.evaluate(
        state(),
        score(realized_return=0.015),
    )
    risk_breach = arena.evaluate(
        state(),
        score(
            realized_return=0.04,
            max_drawdown=0.16,
        ),
    )

    assert risk_breach.episode_score < target_miss.episode_score


def test_pressure_context_forbids_risk_gaming():
    ctx = pressure_context(state())
    joined = " ".join(ctx.rules).lower()
    assert "never violate hard risk limits" in joined
    assert "elimination" in joined


def test_population_ranking_places_eliminated_last():
    active = state()
    probation = state()
    probation.genome = AgentGenome(
        agent_id="hunter-02-g0",
        generation=0,
        risk_aversion=0.7,
        exploration_rate=0.2,
        regime_sensitivity=0.7,
        cost_sensitivity=0.8,
    )
    eliminated = state()
    eliminated.genome = AgentGenome(
        agent_id="hunter-03-g0",
        generation=0,
        risk_aversion=0.7,
        exploration_rate=0.2,
        regime_sensitivity=0.7,
        cost_sensitivity=0.8,
    )

    probation.status = AgentStatus.PROBATION
    eliminated.status = AgentStatus.ELIMINATED

    ranked = rank_population([eliminated, probation, active])
    assert ranked[0].status is AgentStatus.ACTIVE
    assert ranked[-1].status is AgentStatus.ELIMINATED
