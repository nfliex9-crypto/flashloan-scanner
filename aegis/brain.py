from __future__ import annotations

from dataclasses import dataclass
from math import exp


@dataclass(frozen=True)
class BrainVerdict:
    agent_id: str
    trust_score: float
    max_risk_multiplier: float
    action: str
    reasons: tuple[str, ...]


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def evidence_strength(closed_trades: int, updates: int) -> float:
    """Conservative sample-confidence curve; never reaches 1 quickly."""
    trade_strength = 1.0 - exp(-max(0, closed_trades) / 30.0)
    update_strength = 1.0 - exp(-max(0, updates) / 300.0)
    return _clamp(0.75 * trade_strength + 0.25 * update_strength)


def assess_agent(
    *,
    agent_id: str,
    research_score: float,
    timeframe_confirmations: int,
    paper_return: float,
    paper_drawdown: float,
    closed_trades: int,
    paper_updates: int,
    execution_drag_pct: float,
) -> BrainVerdict:
    strength = evidence_strength(closed_trades, paper_updates)
    reasons: list[str] = []

    research = _clamp(research_score / 100.0)
    tf = _clamp(timeframe_confirmations / 3.0)

    forward = 0.50
    if paper_return > 0:
        forward += min(0.25, paper_return * 4.0)
        reasons.append("forward paper PnL positive")
    elif paper_return < 0:
        forward -= min(0.30, abs(paper_return) * 5.0)
        reasons.append("forward paper PnL negative")

    risk = 1.0 - _clamp(paper_drawdown / 0.15)
    if paper_drawdown > 0.08:
        reasons.append("forward drawdown elevated")

    drag = 1.0 - _clamp(execution_drag_pct / 0.02)
    if execution_drag_pct > 0.005:
        reasons.append("execution drag is material")

    # Forward evidence gains weight only as real paper observations accumulate.
    forward_weight = 0.15 + 0.45 * strength
    research_weight = 0.45 - 0.20 * strength
    tf_weight = 0.20
    risk_weight = 0.15
    drag_weight = 0.05

    trust = (
        research_weight * research
        + tf_weight * tf
        + forward_weight * _clamp(forward)
        + risk_weight * risk
        + drag_weight * drag
    )
    trust = round(_clamp(trust) * 100.0, 2)

    # The brain may only REDUCE allowed risk. It cannot raise the immutable base risk.
    risk_multiplier = _clamp((trust - 35.0) / 65.0, 0.0, 1.0)
    if strength < 0.25:
        risk_multiplier = min(risk_multiplier, 0.25)
        reasons.append("forward sample still small")
    elif strength < 0.55:
        risk_multiplier = min(risk_multiplier, 0.50)

    if paper_drawdown >= 0.12 or trust < 40:
        action = "QUARANTINE"
        risk_multiplier = 0.0
    elif trust < 60:
        action = "PROBATION"
    elif strength < 0.35:
        action = "SHADOW_ONLY"
    else:
        action = "PAPER_ELIGIBLE"

    return BrainVerdict(
        agent_id=agent_id,
        trust_score=trust,
        max_risk_multiplier=round(risk_multiplier, 3),
        action=action,
        reasons=tuple(reasons),
    )
