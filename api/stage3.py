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
        if "desk_probe" in query:
            if query != {"desk_probe": ["1"]}:
                self._reply(400, {"ok": False, "error": "invalid_desk_probe_query"})
                return
            try:
                from aegis.stream_probe import get_stream_storage_probe
                self._reply(200, get_stream_storage_probe())
            except Exception:
                self._reply(503, {"ok": False, "error": "paper_probe_unavailable"})
            return
        if "desk" in query:
            if query != {"desk": ["1"]}:
                self._reply(400, {"ok": False, "error": "invalid_paper_desk_query"})
                return
            try:
                from aegis.paper_desk import get_paper_desk
                self._reply(200, get_paper_desk())
            except Exception:
                # Do not disclose Neon URLs or database account details.
                self._reply(503, {"ok": False, "error": "paper_desk_data_unavailable"})
            return
        if "diagnostics" in query:
            if query != {"diagnostics": ["1"]}:
                self._reply(400, {"ok": False, "error": "invalid_diagnostics_query"})
                return
            # Operational canaries inspect persisted Neon receipts only.
            from aegis.ops_health import diagnose
            self._reply(200, diagnose())
            return
        if "mt5_cloud" in query:
            if query != {"mt5_cloud": ["1"]}:
                self._reply(400, {"ok": False, "error": "invalid_mt5_cloud_query"})
                return
            try:
                from aegis.mt5_cloud import public_status, CloudUnavailable
                self._reply(200, public_status())
            except CloudUnavailable:
                self._reply(200, {"ok": True, "state": "CONFIG_INVALID",
                                  "connected": False, "demo_order_execution_enabled": False})
            except Exception:
                self._reply(503, {"ok": False, "error": "metaapi_status_unavailable"})
            return
        if "research_advisors" in query:
            if query != {"research_advisors": ["1"]}:
                self._reply(400, {"ok": False, "error": "invalid_research_advisors_query"})
                return
            from aegis.research_advisory import provider_status
            self._reply(200, provider_status())
            return
        if "capabilities" in query:
            if query != {"capabilities": ["1"]}:
                self._reply(400,{"ok":False,"error":"invalid_capabilities_request"})
                return
            # Public readiness contains no secret values, database URLs, or broker IDs.
            self._reply(200,{"ok":True,"mode":"READ_ONLY_RESEARCH_READINESS",
                "owner_controls_configured":len(os.getenv("AEGIS_CONTROL_TOKEN",""))>=24,
                "demo_order_execution_enabled":False,"live_execution_enabled":False})
            return
        if "backtest" in query:
            mode=query.pop("backtest")
            if mode not in (["1"],["compare"],["walkforward"],["horizon"]):
                self._reply(400,{"ok":False,"error":"invalid_backtest_mode"})
                return
            if any(len(v)!=1 for v in query.values()):
                self._reply(400,{"ok":False,"error":"duplicate_backtest_parameter"})
                return
            try:
                from aegis.backtest_lab import run_backtest,run_strategy_comparison,run_directional_comparison
                from aegis.walkforward_lab import run_walkforward
                params={key:values[0] for key,values in query.items()}
                report=(run_backtest(params) if mode==["1"] else
                        run_directional_comparison(params) if mode==["horizon"] else
                        run_strategy_comparison(params) if mode==["compare"] else
                        run_walkforward(params))
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
        query=parse_qs(urlsplit(self.path).query,keep_blank_values=True)
        if "grok_review" in query:
            if query != {"grok_review": ["1"]}:
                self._reply(400, {"ok": False, "error": "invalid_grok_review_query"})
                return
            auth=authorize_control_request(
                expected_token=os.getenv("AEGIS_CONTROL_TOKEN", ""),
                supplied_auth=self.headers.get("Authorization", ""),
                origin=self.headers.get("Origin", ""),
                host=self.headers.get("Host", ""),
                fetch_site=self.headers.get("Sec-Fetch-Site", ""))
            if auth:
                self._reply(auth[0], {"ok": False, "error": auth[1]})
                return
            # Costed external AI call is opt-in, owner-only and capped per
            # invocation. Input is built from Neon canaries, not request JSON.
            try:
                length=int(self.headers.get("Content-Length", "0"))
                if length < 2 or length > 80 or self.headers.get("Transfer-Encoding"):
                    self._reply(413, {"ok": False, "error": "invalid_grok_payload_size"})
                    return
                body=json.loads(self.rfile.read(length))
                if body != {"action": "review"}:
                    self._reply(400, {"ok": False, "error": "invalid_grok_action"})
                    return
                from aegis.research_advisory import owner_review
                status, report=owner_review()
                self._reply(status, report)
            except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
                self._reply(400, {"ok": False, "error": "invalid_grok_payload"})
            except Exception:
                self._reply(503, {"ok": False, "error": "grok_review_unavailable"})
            return
        if "mt5_cloud" in query:
            if query != {"mt5_cloud": ["1"]}:
                self._reply(400, {"ok": False, "error": "invalid_mt5_cloud_query"})
                return
            try:
                size=int(self.headers.get("Content-Length","0"))
                if size<2 or size>128 or self.headers.get("Transfer-Encoding"):
                    self._reply(413, {"ok": False, "error": "invalid_payload_size"})
                    return
                body=json.loads(self.rfile.read(size))
                if body != {"action":"sync"}:
                    self._reply(400, {"ok": False, "error": "invalid_mt5_cloud_action"})
                    return
                from aegis.mt5_cloud import sync_readonly
                status,result=sync_readonly(self.headers)
                self._reply(status,result)
            except (ValueError,TypeError,UnicodeDecodeError,json.JSONDecodeError):
                self._reply(400, {"ok": False, "error": "invalid_mt5_cloud_request"})
            except Exception:
                self._reply(503, {"ok": False, "error": "metaapi_sync_unavailable"})
            return
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
