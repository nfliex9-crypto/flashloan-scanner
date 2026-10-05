from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from hashlib import sha256
from typing import Iterable


class AgentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    ELIMINATED = "ELIMINATED"


@dataclass(frozen=True)
class AgentGenome:
    agent_id: str
    generation: int
    risk_aversion: float
    exploration_rate: float
    regime_sensitivity: float
    cost_sensitivity: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class AgentScore:
    target_return: float
    realized_return: float
    max_drawdown: float
    max_allowed_drawdown: float
    rule_violations: int = 0
    falsification_failures: int = 0
    paper_days: int = 0

    @property
    def target_attainment(self) -> float:
        if self.target_return <= 0:
            return 1.0
        return self.realized_return / self.target_return


@dataclass
class AgentState:
    genome: AgentGenome
    status: AgentStatus = AgentStatus.ACTIVE
    strikes: int = 0
    lifetime_score: float = 100.0
    history: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class SelectionDecision:
    agent_id: str
    status: AgentStatus
    strikes: int
    episode_score: float
    lifetime_score: float
    action: str
    reason: str
    replacement: AgentGenome | None = None


class SurvivalArena:
    """Performance-pressure engine for research agents.

    It creates *selection pressure*, not literal fear. Agents remain eligible only
    while they meet performance and robustness requirements. Risk violations are
    punished more heavily than missing a return target so the system cannot game
    survival by taking reckless risk.
    """

    def __init__(
        self,
        *,
        strike_limit: int = 3,
        probation_threshold: float = 70.0,
        eliminate_threshold: float = 50.0,
    ) -> None:
        self.strike_limit = strike_limit
        self.probation_threshold = probation_threshold
        self.eliminate_threshold = eliminate_threshold

    def evaluate(self, state: AgentState, score: AgentScore) -> SelectionDecision:
        penalties = 0.0
        rewards = 0.0
        reasons: list[str] = []

        attainment = score.target_attainment

        # Missing the target matters, but never as much as violating risk limits.
        if attainment < 1.0:
            gap = min(1.0, max(0.0, 1.0 - attainment))
            penalties += 25.0 * gap
            reasons.append(f"target shortfall: {attainment:.1%} achieved")
        else:
            rewards += min(10.0, 4.0 + (attainment - 1.0) * 8.0)
            reasons.append(f"target achieved: {attainment:.1%}")

        if score.max_drawdown > score.max_allowed_drawdown:
            excess = score.max_drawdown / max(score.max_allowed_drawdown, 1e-12)
            penalties += min(45.0, 20.0 * excess)
            reasons.append(
                f"drawdown breach: {score.max_drawdown:.2%} > "
                f"{score.max_allowed_drawdown:.2%}"
            )

        if score.rule_violations:
            penalties += min(60.0, 25.0 * score.rule_violations)
            reasons.append(f"hard-rule violations: {score.rule_violations}")

        if score.falsification_failures:
            penalties += min(30.0, 8.0 * score.falsification_failures)
            reasons.append(f"red-team failures: {score.falsification_failures}")

        if score.paper_days >= 30:
            rewards += 5.0
            reasons.append("30+ paper days")

        episode_score = round(
            max(0.0, min(100.0, 100.0 - penalties + rewards)),
            2,
        )
        state.lifetime_score = round(
            0.65 * state.lifetime_score + 0.35 * episode_score,
            2,
        )

        failed_episode = (
            episode_score < self.probation_threshold
            or score.rule_violations > 0
            or score.max_drawdown > score.max_allowed_drawdown
        )

        if failed_episode:
            state.strikes += 1
        else:
            state.strikes = max(0, state.strikes - 1)

        replacement = None
        if (
            state.strikes >= self.strike_limit
            or state.lifetime_score < self.eliminate_threshold
            or score.rule_violations >= 2
        ):
            state.status = AgentStatus.ELIMINATED
            replacement = self.spawn_replacement(state.genome)
            action = "ELIMINATE_AND_REPLACE"
        elif state.strikes > 0 or state.lifetime_score < self.probation_threshold:
            state.status = AgentStatus.PROBATION
            action = "PROBATION"
        else:
            state.status = AgentStatus.ACTIVE
            action = "KEEP_ACTIVE"

        record = {
            "episode_score": episode_score,
            "lifetime_score": state.lifetime_score,
            "strikes": state.strikes,
            "status": state.status.value,
            "action": action,
            "target_attainment": round(attainment, 6),
            "max_drawdown": score.max_drawdown,
            "rule_violations": score.rule_violations,
            "falsification_failures": score.falsification_failures,
        }
        state.history.append(record)

        return SelectionDecision(
            agent_id=state.genome.agent_id,
            status=state.status,
            strikes=state.strikes,
            episode_score=episode_score,
            lifetime_score=state.lifetime_score,
            action=action,
            reason="; ".join(reasons),
            replacement=replacement,
        )

    def spawn_replacement(self, parent: AgentGenome) -> AgentGenome:
        """Create a deterministic mutated successor so failed agents are replaced."""
        child_generation = parent.generation + 1
        digest = sha256(
            f"{parent.agent_id}:{child_generation}".encode("utf-8")
        ).hexdigest()

        # Deterministic mutations bounded to sane research ranges.
        def mutation(offset: int, scale: float) -> float:
            raw = int(digest[offset : offset + 4], 16) / 65535.0
            return (raw - 0.5) * scale

        risk = min(0.95, max(0.05, parent.risk_aversion + mutation(0, 0.16)))
        explore = min(0.80, max(0.02, parent.exploration_rate + mutation(4, 0.14)))
        regime = min(0.95, max(0.05, parent.regime_sensitivity + mutation(8, 0.16)))
        cost = min(0.95, max(0.05, parent.cost_sensitivity + mutation(12, 0.16)))

        child_id = f"{parent.agent_id.split('-g')[0]}-g{child_generation}"
        return AgentGenome(
            agent_id=child_id,
            generation=child_generation,
            risk_aversion=round(risk, 4),
            exploration_rate=round(explore, 4),
            regime_sensitivity=round(regime, 4),
            cost_sensitivity=round(cost, 4),
        )


def rank_population(states: Iterable[AgentState]) -> list[AgentState]:
    """Rank survivors without allowing eliminated agents to lead the population."""
    priority = {
        AgentStatus.ACTIVE: 2,
        AgentStatus.PROBATION: 1,
        AgentStatus.ELIMINATED: 0,
    }
    return sorted(
        states,
        key=lambda s: (priority[s.status], s.lifetime_score, -s.strikes),
        reverse=True,
    )
