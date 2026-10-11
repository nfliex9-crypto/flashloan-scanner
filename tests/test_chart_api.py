import io
import json
from api.stage3 import handler
from aegis import chart_store


class Request:
    def __init__(self,path,body=b'{}',headers=None):
        self.path=path;self.headers={'Content-Length':str(len(body)),**(headers or {})}
        self.rfile=io.BytesIO(body);self.result=None
    def _reply(self,code,body,cache='no-store'):self.result=(code,body)


def test_cannot_smuggle_chart_request_into_trading_or_settings_route():
    for method in (handler.do_GET,handler.do_POST):
        req=Request('/api/stage3?chart=1&mt5_cloud=1');method(req)
        assert req.result[0]==400


def test_ingest_requires_auth_before_parsing_or_storing(monkeypatch):
    monkeypatch.delenv('AEGIS_CHART_TOKEN',raising=False)
    req=Request('/api/stage3?chart=1',b'{"source":"TRADINGVIEW_DESKTOP"}')
    handler.do_POST(req)
    assert req.result[0]==401


def test_oversize_body_rejected_before_read(monkeypatch):
    req=Request('/api/stage3?chart=1',headers={'Content-Length':'5000000'})
    handler.do_POST(req);assert req.result[0]==413


def test_read_does_not_authorize_broker_execution(monkeypatch):
    monkeypatch.setattr(chart_store,'status',lambda:{'ok':True,'snapshots':[],'execution_enabled':False})
    req=Request('/api/stage3?chart=1');handler.do_GET(req)
    assert req.result==(200,{'ok':True,'snapshots':[],'execution_enabled':False})
