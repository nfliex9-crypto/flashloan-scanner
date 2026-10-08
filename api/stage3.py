from __future__ import annotations
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlsplit,parse_qs

from aegis.stage3 import get_stage3_state
from aegis.experiments import save_controls


def authorize_control_request(*, expected_token: str, supplied_auth: str, origin: str,
                              host: str, fetch_site: str) -> tuple[int, str] | None:
    """Hard gate: an explicit separate owner key, origin check, no weak defaults."""
    if len(expected_token)<24:
        return 503,"owner_control_key_not_configured"
    if fetch_site and fetch_site not in ("same-origin","none"):
        return 403,"cross_site_requests_blocked"
    if origin:
        try:
            p=urlsplit(origin)
            if p.scheme!="https" or p.netloc.lower()!=host.lower():
                return 403,"origin_mismatch"
        except ValueError:
            return 403,"origin_mismatch"
    if not hmac.compare_digest(supplied_auth, "Bearer "+expected_token):
        return 401,"unauthorized"
    return None


class handler(BaseHTTPRequestHandler):
    def _reply(self,status: int,payload:dict,cache:str="no-store"):
        data=json.dumps(payload,default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Cache-Control",cache)
        self.send_header("X-Content-Type-Options","nosniff")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        # Reuse the existing function slot. Read-only, bounded historical
        # testing cannot touch a broker or persist simulated fills in Neon.
        query=parse_qs(urlsplit(self.path).query,keep_blank_values=True)
        if "backtest" in query:
            if query.pop("backtest")!=["1"]:
                self._reply(400,{"ok":False,"error":"invalid_backtest_mode"})
                return
            if any(len(v)!=1 for v in query.values()):
                self._reply(400,{"ok":False,"error":"duplicate_backtest_parameter"})
                return
            try:
                from aegis.backtest_lab import run_backtest
                report=run_backtest({key:values[0] for key,values in query.items()})
                self._reply(200,report,cache="public, s-maxage=300, stale-while-revalidate=120")
            except ValueError as exc:
                # Only finite, authored validation messages. Never return
                # upstream network errors or token-bearing URLs.
                self._reply(422,{"ok":False,"error":str(exc)[:150]})
            except Exception:
                self._reply(503,{"ok":False,"error":"backtest_data_temporarily_unavailable"})
            return
        try:
            self._reply(200,get_stage3_state())
        except Exception:
            self._reply(503,{"ok":False,"error":"ledger_temporarily_unavailable"})

    def do_POST(self):
        check=authorize_control_request(
            expected_token=os.getenv("AEGIS_CONTROL_TOKEN",""),
            supplied_auth=self.headers.get("Authorization",""),
            origin=self.headers.get("Origin",""),
            host=self.headers.get("Host",""),
            fetch_site=self.headers.get("Sec-Fetch-Site",""))
        if check:
            self._reply(check[0],{"ok":False,"error":check[1]})
            return
        try:
            size=int(self.headers.get("Content-Length","0"))
            if size<=0 or size>2048:
                self._reply(413,{"ok":False,"error":"invalid_content_length"})
                return
            raw=self.rfile.read(size)
            body=json.loads(raw.decode("utf-8"))
            result=save_controls(body)
            self._reply(200,{"ok":True,"saved":result,"mode":"SHADOW_RESEARCH_ONLY",
                             "live_execution_enabled":False})
        except (ValueError,TypeError,UnicodeDecodeError,json.JSONDecodeError):
            self._reply(400,{"ok":False,"error":"invalid_experiment_configuration"})
        except Exception:
            self._reply(503,{"ok":False,"error":"settings_temporarily_unavailable"})
