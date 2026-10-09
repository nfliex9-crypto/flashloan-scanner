"""Immutable pre-forward screens from real source candles, not virtual fills."""
import hashlib
import json
from datetime import datetime,timezone
from .backtest_lab import simulate_costed_backtest
from .walkforward_lab import verify_walkforward
from .horizon_selector import TIMEFRAME_MINUTES,MIN_SAMPLE_DAYS
from .directional_signals import classify_horizon
from .stream_paper import STRATEGIES,MICRO_DIRECTIONS,stream_agent_id


def build_receipts(symbol,minutes,bars,now=None):
    # BTC uses the cost model validated by backtest_lab. ETH has no matching
    # historical instrument model yet and must not borrow BTC's evidence.
    if symbol!='BTC' or len(bars)<180:return []
    now=now or datetime.now(timezone.utc)
    interval=TIMEFRAME_MINUTES[minutes]
    split=max(65,int(len(bars)*.7))
    days=(bars[-1].ts+minutes*60-bars[split].ts)/86400
    if bars[-1].ts+minutes*60>now.timestamp():raise ValueError('Incomplete historical bar')
    history_hash=hashlib.sha256(json.dumps([vars(b) for b in bars],sort_keys=True).encode()).hexdigest()
    receipts=[]
    for strategy in STRATEGIES:
        for direction in MICRO_DIRECTIONS:
            kwargs=dict(asset=symbol,strategy=strategy,interval=interval,direction=direction)
            base=simulate_costed_backtest(bars,**kwargs,entry_from=split)['stats']
            stress=simulate_costed_backtest(bars,**kwargs,entry_from=split,cost_multiplier=2)['stats']
            folds=verify_walkforward(bars,**kwargs)
            passed=(base['trades']>=20 and base['closed_net_pnl']>0 and base['profit_factor']>=1.25
                    and stress['closed_net_pnl']>0 and max(base['max_drawdown_pct'],stress['max_drawdown_pct'])<4
                    and days>=MIN_SAMPLE_DAYS[classify_horizon(interval)] and folds['folds_passed']==3)
            receipt={**kwargs,'agent_id':stream_agent_id(symbol,minutes,strategy,direction),
                     'evaluated_at':now.isoformat(),'history_hash':history_hash,
                     'source':'Kraken XBTUSD closed historical OHLC','bars':len(bars),
                     'holdout_days':days,'holdout':base,'stress_holdout':stress,
                     'walkforward':folds,'historical_screen_passed':passed}
            receipt['evidence_hash']=hashlib.sha256(json.dumps(receipt,sort_keys=True,allow_nan=False).encode()).hexdigest()
            receipts.append(receipt)
    return receipts


def persist_receipts(conn,receipts):
    with conn.transaction():
        with conn.cursor() as cur:
            for receipt in receipts:
                cur.execute('INSERT INTO aegis.stream_historical_screens(agent_id,evaluated_at,evidence) '
                            'VALUES(%s,%s,%s::jsonb) ON CONFLICT(agent_id) DO NOTHING',
                            (receipt['agent_id'],receipt['evaluated_at'],json.dumps(receipt,allow_nan=False)))
