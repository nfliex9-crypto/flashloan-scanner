"""First-class AEGIS strategy bots remain backed by real virtual receipts.

All fixtures are explicitly synthetic for unit tests; no test result is
exposed as a simulated account's historical performance.
"""
from aegis.bot_fleet import project_paper_bots


def account(name="bot1", interval=5, halted=False, direction="LONG"):
    return {"agent_id":name,"symbol":"BTC","interval_minutes":interval,
            "strategy":"EMA Cross","direction":direction,
            "cash":99820.0,"max_drawdown":0.01,"halted":halted}


def closed(name="bot1", trades=25, net=125, wins=200, losses=-75):
    return {"agent_id":name,"trades":trades,"net_pnl":net,
            "gross_gains":wins,"gross_losses":losses}


def candidate(name="bot1", selected=True):
    return {"agent_id":name,"selection_qualified":selected}


def test_bot_maps_account_to_independent_strategy_and_realized_costed_results():
    bots=project_paper_bots([account()], [closed()], [], [5], [candidate()])
    assert len(bots)==1
    bot=bots[0]
    assert bot["bot_id"]=="bot1"
    assert bot["strategy"]=="EMA Cross"
    assert bot["interval_minutes"]==5
    assert bot["direction"]=="LONG"
    assert bot["state"]=="PAPER_OBSERVING"
    assert bot["closed_trades"]==25
    assert bot["net_pnl_after_costs"]==125
    assert bot["average_net_per_closed_trade"]==5
    assert bot["profit_factor"]==round(200/75,4)
    assert bot["oos_forward_qualified"] is True
    assert bot["trade_order_permission"] is False
    assert bot["execution_mode"]=="KRAKEN_VIRTUAL_PAPER_ONLY"


def test_bot_performance_not_invented_when_no_closed_trades():
    bots=project_paper_bots([account()],[],[],[5],[])
    bot=bots[0]
    assert bot["closed_trades"]==0
    assert bot["net_pnl_after_costs"] is None
    assert bot["average_net_per_closed_trade"] is None
    assert bot["profit_factor"] is None
    assert bot["state"]=="COLLECTING_FORWARD"
    assert bot["oos_forward_qualified"] is False


def test_feed_staleness_overrules_positive_backtest():
    bots=project_paper_bots([account()], [closed()],[],[],[candidate()])
    assert bots[0]["state"]=="FEED_UNVERIFIED"
    assert bots[0]["oos_forward_qualified"] is False
    assert bots[0]["trade_order_permission"] is False


def test_risk_halt_blocks_qualification_even_with_good_results_and_feed():
    bots=project_paper_bots([account(halted=True)], [closed()],[],[5],[candidate()])
    assert bots[0]["state"]=="HALTED_RISK"
    assert bots[0]["oos_forward_qualified"] is False


def test_legacy_1m_accounts_are_excluded_while_5m_long_short_remain_independent():
    acc=[
        account("legacy-btc-1m-long",1,direction="LONG"),
        account("legacy-btc-1m-short",1,direction="SHORT"),
        account("btc-5m-long",5,direction="LONG"),
        account("btc-5m-short",5,direction="SHORT"),
    ]
    trades=[closed("legacy-btc-1m-long",net=25),
            closed("legacy-btc-1m-short",net=-50),
            closed("btc-5m-short",net=75)]
    bots=project_paper_bots(acc,trades,[],[1,5],[])
    ids={b["bot_id"] for b in bots}
    assert ids=={"btc-5m-long","btc-5m-short"}
    assert next(x for x in bots if x["bot_id"]=="btc-5m-short")["net_pnl_after_costs"]==75
    assert all(b["interval_minutes"]>=5 for b in bots)


def test_open_position_is_paper_only_not_broker_position():
    bot=project_paper_bots([account()],[],[{"agent_id":"bot1","qty":0.1}],[5],[])[0]
    assert bot["state"]=="OPEN_PAPER_POSITION"
    assert bot["paper_position_open"] is True
    assert bot["trade_order_permission"] is False


def test_nonstrategy_accounts_and_fake_assets_cannot_create_bots():
    malicious=[
        {**account("other"),"strategy":"unapproved AI arbitrary code"},
        {**account("gold"),"symbol":"XAUUSD"},
        {**account("wrong"),"direction":"BOTH"},
        {**account("badtime"),"interval_minutes":3},
        {"agent_id":"incomplete"},
    ]
    assert project_paper_bots(malicious,[],[],[5],[])==[]


def test_positive_pnl_is_not_sufficient_for_an_oos_qualified_bot():
    bot=project_paper_bots([account()], [closed()],[],[5],
                            [{"agent_id":"bot1","qualified":True,
                              "selection_qualified":False}])[0]
    assert bot["net_pnl_after_costs"]==125
    assert bot["oos_forward_qualified"] is False


def test_profit_factor_is_undefined_without_losing_trades():
    bot=project_paper_bots([account()], [closed(losses=0)],[],[5],[candidate()])[0]
    assert bot["profit_factor"] is None
    assert bot["profit_factor_defined"] is False


def test_short_forward_sample_never_qualifies():
    bot=project_paper_bots([account()], [closed(trades=3)],[],[5],[candidate()])[0]
    assert bot["forward_sample_sufficient"] is False
    assert bot["oos_forward_qualified"] is False


def test_nonfinite_performance_never_becomes_profitable_label():
    bot=project_paper_bots([account()], [closed(net=float("nan"),wins=float("inf"))],
                            [],[5],[])[0]
    assert bot["net_pnl_after_costs"]==0
    assert bot["profit_factor"]==0


def test_invalid_active_timeframes_are_rejected_not_implicitly_enabled():
    bot=project_paper_bots([account()],[],[],["5",True,999],[])[0]
    assert bot["feed_verified"] is False
    assert bot["state"]=="FEED_UNVERIFIED"
