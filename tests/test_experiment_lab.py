"""Experiment lab tests: bounded trials, controls auth, no broker permissions."""
from datetime import datetime,timezone

import pytest

from aegis.experiments import (
    EXPERIMENT_STRATEGIES, select_experiment_agents,validate_controls,
)
from aegis.live_lab import Candle,strategy_positions
from api.stage3 import authorize_control_request


def series(n=290):
    price=100.0
    out=[]
    for i in range(n):
        price*=1+(.001 if i%90<55 else -.0015)
        out.append(Candle(ts=1700000000+i*3600,open=price*.999,
            high=price*1.002,low=price*.998,close=price,volume=200+i))
    return out


def config(**kw):
    return {"enabled":kw.get("enabled",True),
            "assets":kw.get("assets",["BTC","XAU"]),
            "strategies":kw.get("strategies",list(EXPERIMENT_STRATEGIES)),
            "max_candidates":kw.get("max_candidates",6)}


def test_each_new_strategy_is_causal_deterministic_and_binary():
    xs=[c.close for c in series()]
    for name in EXPERIMENT_STRATEGIES:
        a=strategy_positions(xs,name)
        assert len(a)==len(xs)
        assert set(a)<={0,1}
        for n in (150,220):
            assert strategy_positions(xs[:n],name)==a[:n]


def test_bounded_shadow_agents_without_main_broker_entitlement():
    agents=select_experiment_agents({"BTC":series(),"XAU":series()},config())
    assert len(agents)==6
    assert len({a["agent_id"] for a in agents})==6
    assert all(a["shadow_only"] and a["experimental"] for a in agents)
    assert all(a["asset"] in ("BTC","XAU") for a in agents)


def test_pause_and_limit_are_real_constraints():
    assert not select_experiment_agents({"BTC":series()},config(enabled=False))
    a=select_experiment_agents({"BTC":series(),"XAU":series()},config(max_candidates=2))
    assert len(a)==2
    assert len(select_experiment_agents({"XAU":series()},config(assets=["XAU"])))==3


def test_research_controls_fail_closed_on_invalid_fields():
    for value in (config(max_candidates=200),config(assets=[]),
                  config(strategies=["Live Order"]),config(max_candidates=True)):
        with pytest.raises(ValueError):
            validate_controls(value)
    with pytest.raises(ValueError):
        validate_controls({**config(),"risk_per_trade":1})


def test_owner_key_and_same_origin_required():
    secret="this-is-only-a-unit-test-key-not-used-on-vercel"
    ok=authorize_control_request(expected_token=secret,supplied_auth="Bearer "+secret,
                                 origin="https://example.vercel.app",
                                 host="example.vercel.app",fetch_site="same-origin")
    assert ok is None
    assert authorize_control_request(expected_token="",supplied_auth="Bearer hi",
               origin="",host="example.vercel.app",fetch_site="same-origin")[0]==503
    assert authorize_control_request(expected_token=secret,supplied_auth="Bearer bad",
               origin="https://example.vercel.app",host="example.vercel.app",
               fetch_site="same-origin")[0]==401
    assert authorize_control_request(expected_token=secret,supplied_auth="Bearer "+secret,
               origin="https://evil.example",host="example.vercel.app",
               fetch_site="cross-site")[0]==403
