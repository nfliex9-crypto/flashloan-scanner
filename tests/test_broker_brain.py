import os

import pytest

from aegis.alpaca_paper import ALLOWED_CRYPTO, PAPER_BASE_URL, place_market_order
from aegis.brain import assess_agent, evidence_strength


def test_broker_is_hardcoded_to_paper_domain():
    assert PAPER_BASE_URL == "https://paper-api.alpaca.markets"
    assert "BTC/USD" in ALLOWED_CRYPTO


def test_paper_order_rejects_unsupported_symbol_before_network(monkeypatch):
    monkeypatch.setenv("ALPACA_PAPER_API_KEY", "fake")
    monkeypatch.setenv("ALPACA_PAPER_API_SECRET", "fake")
    with pytest.raises(ValueError):
        place_market_order(symbol="DOGE/EUR", side="buy", notional_usd=10)


def test_brain_never_increases_base_risk():
    verdict = assess_agent(
        agent_id="test",
        research_score=99,
        timeframe_confirmations=3,
        paper_return=0.20,
        paper_drawdown=0.01,
        closed_trades=500,
        paper_updates=5000,
        execution_drag_pct=0.0,
    )
    assert 0 <= verdict.max_risk_multiplier <= 1.0


def test_small_sample_caps_brain_risk():
    verdict = assess_agent(
        agent_id="test",
        research_score=95,
        timeframe_confirmations=3,
        paper_return=0.10,
        paper_drawdown=0.01,
        closed_trades=0,
        paper_updates=5,
        execution_drag_pct=0.0,
    )
    assert verdict.max_risk_multiplier <= 0.25
    assert verdict.action in {"SHADOW_ONLY", "PROBATION", "QUARANTINE"}


def test_evidence_strength_grows_with_forward_data():
    assert evidence_strength(50, 500) > evidence_strength(1, 5)
