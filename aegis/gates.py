from __future__ import annotations

from dataclasses import dataclass

from .models import PromotionLevel, StrategyEvidence
from .survival import survival_score


@dataclass(frozen=True)
class GateResult:
    name: str
    passed: bool
    actual: float | int
    threshold: str


@dataclass(frozen=True)
class Verdict:
    level: PromotionLevel
    score: float
    gates: tuple[GateResult, ...]

    @property
    def passed_all(self) -> bool:
        return all(g.passed for g in self.gates)


def evaluate(e: StrategyEvidence) -> Verdict:
    gates = (
        GateResult("trade_count", e.total_trades >= 200, e.total_trades, ">= 200"),
        GateResult("max_drawdown", e.max_drawdown <= 0.10, e.max_drawdown, "<= 10%"),
        GateResult("profit_factor", e.profit_factor >= 1.25, e.profit_factor, ">= 1.25"),
        GateResult(
            "deflated_sharpe",
            e.deflated_sharpe_confidence >= 0.95,
            e.deflated_sharpe_confidence,
            ">= 0.95",
        ),
        GateResult("pbo", e.pbo <= 0.20, e.pbo, "<= 0.20"),
        GateResult(
            "cost_survival",
            e.cost_survival_multiple >= 2.0,
            e.cost_survival_multiple,
            ">= 2x costs",
        ),
        GateResult(
            "parameter_stability",
            e.parameter_stability >= 0.70,
            e.parameter_stability,
            ">= 0.70",
        ),
        GateResult(
            "regime_pass_rate",
            e.regime_pass_rate >= 0.70,
            e.regime_pass_rate,
            ">= 0.70",
        ),
        GateResult(
            "ruin_probability",
            e.ruin_probability <= 0.01,
            e.ruin_probability,
            "<= 1%",
        ),
    )

    core_pass = all(g.passed for g in gates)
    score = survival_score(e)

    if not core_pass:
        level = PromotionLevel.REJECTED
    elif e.paper_days < 14:
        level = PromotionLevel.RESEARCH
    elif e.paper_days < 30 or e.paper_return <= 0 or abs(e.live_drift_z) > 2.5:
        level = PromotionLevel.SHADOW
    else:
        level = PromotionLevel.CANARY_ELIGIBLE

    return Verdict(level=level, score=score, gates=gates)


def capital_firewall(verdict: Verdict) -> float:
    """Maximum capital fraction the research engine is allowed to request.

    Live execution is intentionally not implemented. This is a policy output only.
    """
    if verdict.level is PromotionLevel.CANARY_ELIGIBLE and verdict.score >= 80:
        return 0.0025  # 0.25% canary risk budget, still requires separate live approval.
    return 0.0
