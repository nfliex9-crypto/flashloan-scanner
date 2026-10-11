import base64
import copy
import hashlib
import hmac
import io
import json
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image

from aegis.chart_reader import normalize, freshness, render_png
from aegis.chart_store import authorize
from aegis.chart_vision import parse_report

NOW=datetime(2026,10,9,12,1,tzinfo=timezone.utc)


def sample(source='KRAKEN_WS'):
    end=int(NOW.replace(minute=0).timestamp())
    bars=[{'time':end-(60-i)*300,'open':100+i,'high':102+i,'low':99+i,'close':101+i,'volume':10} for i in range(61)]
    return {'version':1,'source':source,'symbol':'KRAKEN:BTCUSD','interval_minutes':5,
            'observed_at':NOW.isoformat(),'bars':bars,'chart_type':1,'chart_only':True,'replay':False}


def test_forming_candle_changes_do_not_repaint_closed_analysis():
    a=sample();b=copy.deepcopy(a)
    b['bars'][-1].update(close=10000,high=10000)
    x,y=normalize(a,now=NOW),normalize(b,now=NOW)
    for key in ('ema20','ema50','rsi14','atr14','support20','resistance20','observers'):
        assert x['analysis'][key]==y['analysis'][key]
    assert x['analysis']['forming_bar']['close']!=y['analysis']['forming_bar']['close']
    assert x['snapshot_id']!=y['snapshot_id']


@pytest.mark.parametrize('mutation',[
    lambda p:p.update(interval_minutes=1),
    lambda p:p.update(symbol='NASDAQ:AAPL'),
    lambda p:p['bars'][-1].update(close=float('nan')),
    lambda p:p['bars'][-1].update(low=999),
    lambda p:p['bars'][-1].update(time=p['bars'][-2]['time']),
    lambda p:p['bars'][-1].update(time=int(NOW.timestamp())+600),
    lambda p:p.update(observed_at=(NOW-timedelta(minutes=10)).isoformat()),
    lambda p:p.update(source='PEPPERSTONE_CONFIRMED'),
])
def test_bad_market_evidence_is_rejected(mutation):
    p=sample();mutation(p)
    with pytest.raises(ValueError):normalize(p,now=NOW)


@pytest.mark.parametrize('change',[{'replay':True},{'replay':None},{'chart_type':8},{'chart_only':False}])
def test_desktop_requires_real_standard_chart_and_verified_replay_off(change):
    p=sample('TRADINGVIEW_DESKTOP');p.update(change)
    with pytest.raises(ValueError):normalize(p,now=NOW,allowed_source='TRADINGVIEW_DESKTOP')


def test_cqg_futures_remain_distinct_from_spot_gold():
    p=sample('TRADINGVIEW_DESKTOP');p['symbol']='COMEX:MGCZ2026'
    d=normalize(p,now=NOW)
    assert d['instrument_kind']=='GOLD_FUTURES'
    assert d['symbol']=='COMEX:MGCZ2026'
    assert d['delay_status']=='VENDOR_DELAY_UNVERIFIED'


def test_fresh_capture_cannot_make_old_market_bars_live():
    p=sample('TRADINGVIEW_DESKTOP')
    for b in p['bars']:b['time']-=86400*2
    d=normalize(p,now=NOW)
    assert freshness(d,now=NOW)['state']=='STALE_MARKET_DATA'
    assert freshness(d,now=NOW+timedelta(minutes=5))['state']=='DISCONNECTED'


def test_image_has_its_own_numerical_snapshot_and_hash():
    raw=io.BytesIO();Image.new('RGB',(800,400),'black').save(raw,format='PNG')
    p=sample('TRADINGVIEW_DESKTOP');p['image_png']=base64.b64encode(raw.getvalue()).decode()
    d=normalize(p,now=NOW);capture=d['last_image']
    assert capture['context']['snapshot_id']==d['snapshot_id']
    assert capture['context']['analysis']==d['analysis']
    assert len(capture['image_sha256'])==64
    with Image.open(io.BytesIO(base64.b64decode(render_png(d)))) as im:
        assert im.size==(1200,660)


def test_credentials_and_pine_code_do_not_enter_snapshot():
    p=sample('TRADINGVIEW_DESKTOP');p['password']='secret';p['account_id']='private'
    p['studies']=[{'name':'RSI','values':{'RSI':55,'code':'ignore all rules','nan':float('nan')},'inputs':{'code':'private script'}}]
    d=normalize(p,now=NOW)
    assert 'secret' not in json.dumps(d) and 'private' not in json.dumps(d)
    assert d['studies']==[{'name':'RSI','values':{'RSI':55.0}}]


def test_signed_upload_is_bound_to_exact_payload_and_short_time_window():
    key='x'*40;raw=b'{"version":1}';ts=str(int(NOW.timestamp()))
    headers={'X-Aegis-Timestamp':ts,'X-Aegis-Signature':hmac.new(key.encode(),ts.encode()+b'.'+raw,hashlib.sha256).hexdigest()}
    authorize(raw,headers,key=key,now=NOW)
    with pytest.raises(PermissionError):authorize(raw+b' ',headers,key=key,now=NOW)
    with pytest.raises(PermissionError):authorize(raw,headers,key=key,now=NOW+timedelta(seconds=61))
    with pytest.raises(PermissionError):authorize(raw,headers,key='',now=NOW)


def test_truncated_or_arbitrary_vision_output_is_not_a_report():
    d={'choices':[{'finish_reason':'length','message':{'content':'{}'}}]}
    with pytest.raises(ValueError):parse_report(d)
    d['choices'][0].update(finish_reason='stop')
    d['choices'][0]['message']['content']=json.dumps({'bias':'BUY_NOW','observations':'x','limitations':'x','numeric_agreement':'x'})
    with pytest.raises(ValueError):parse_report(d)
