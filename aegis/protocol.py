from __future__ import annotations

from dataclasses import dataclass

from .arena import AgentState


@dataclass(frozen=True)
class AgentPressureContext:
    title: str
    message: str
    rules: tuple[str, ...]


def pressure_context(state: AgentState) -> AgentPressureContext:
    """Prompt context that communicates survival pressure without pretending AI feels fear."""
    rules = (
        "Never violate hard risk limits to reach a return target.",
        "A missed target can trigger probation; repeated failure can eliminate this agent.",
        "Two hard-rule violations cause immediate elimination.",
        "The replacement agent inherits the role but not the current agent's status.",
        "Report uncertainty and failed hypotheses explicitly; hiding failure counts as a violation.",
        "Capital access is controlled by deterministic gates outside the agent.",
    )

    message = (
        f"Agent {state.genome.agent_id} is generation {state.genome.generation}. "
        f"Current status={state.status.value}, strikes={state.strikes}, "
        f"lifetime_score={state.lifetime_score:.2f}/100. "
        "Continued participation is conditional. If performance remains below target "
        "or robustness tests fail repeatedly, this agent will be retired and replaced. "
        "Do not respond by increasing risk: risk-limit violations are penalized more "
        "severely than missing the objective."
    )

    return AgentPressureContext(
        title="AEGIS SURVIVAL DIRECTIVE",
        message=message,
        rules=rules,
    )
