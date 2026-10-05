from __future__ import annotations

from .arena import AgentGenome, AgentScore, AgentState, SurvivalArena
from .protocol import pressure_context


def main() -> None:
    arena = SurvivalArena(strike_limit=3)

    state = AgentState(
        genome=AgentGenome(
            agent_id="hunter-01-g0",
            generation=0,
            risk_aversion=0.72,
            exploration_rate=0.24,
            regime_sensitivity=0.68,
            cost_sensitivity=0.81,
        )
    )

    episodes = (
        AgentScore(
            target_return=0.03,
            realized_return=0.018,
            max_drawdown=0.055,
            max_allowed_drawdown=0.08,
            falsification_failures=1,
        ),
        AgentScore(
            target_return=0.03,
            realized_return=0.012,
            max_drawdown=0.083,
            max_allowed_drawdown=0.08,
            falsification_failures=2,
        ),
        AgentScore(
            target_return=0.03,
            realized_return=0.009,
            max_drawdown=0.072,
            max_allowed_drawdown=0.08,
            falsification_failures=2,
        ),
    )

    print("AEGIS AGENT SURVIVAL ARENA")
    print("=" * 62)
    print(pressure_context(state).message)

    for index, score in enumerate(episodes, start=1):
        decision = arena.evaluate(state, score)
        print(
            f"episode={index} action={decision.action} "
            f"episode_score={decision.episode_score:.2f} "
            f"lifetime={decision.lifetime_score:.2f} strikes={decision.strikes}"
        )
        print(f"  reason: {decision.reason}")

        if decision.replacement:
            child = decision.replacement
            print(
                f"  replacement spawned: {child.agent_id} "
                f"(generation {child.generation})"
            )
            break


if __name__ == "__main__":
    main()
