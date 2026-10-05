from __future__ import annotations

import json
import urllib.request
from http.server import BaseHTTPRequestHandler

from aegis.brain import assess_agent


PAPER_URL = (
    "https://raw.githubusercontent.com/"
    "nfliex9-crypto/flashloan-scanner/"
    "paper-state/data/paper_state.json"
)
EVOLUTION_URL = (
    "https://raw.githubusercontent.com/"
    "nfliex9-crypto/flashloan-scanner/"
    "evolution-state/data/evolution_state.json"
)


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "AEGIS-Evidence-Brain/1.0"},
    )
    with urllib.request.urlopen(request, timeout=7) as response:
        return json.loads(response.read().decode("utf-8"))


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            paper = fetch_json(PAPER_URL)
            evolution = fetch_json(EVOLUTION_URL)

            paper_agents = paper.get("agents", {})
            evo_records = evolution.get("incumbents", {})

            rows = []
            for family, record in evo_records.items():
                symbol = record.get("symbol", "")
                strategy = record.get("strategy", "")
                variant = int(record.get("genome", {}).get("generation", 0))

                candidates = [
                    a
                    for a in paper_agents.values()
                    if a.get("asset") == symbol
                    and a.get("strategy") == strategy
                ]
                pa = candidates[0] if candidates else None

                if pa:
                    initial = float(pa.get("initial_equity") or 10_000)
                    equity = float(pa.get("equity") or initial)
                    paper_return = equity / initial - 1.0 if initial else 0.0
                    drag = (
                        float(pa.get("total_fees_usd") or 0)
                        + float(pa.get("total_slippage_usd") or 0)
                    ) / initial if initial else 0.0
                    paper_dd = float(pa.get("max_drawdown") or 0)
                    closed_trades = int(pa.get("closed_trades") or 0)
                    updates = int(pa.get("updates") or 0)
                    agent_id = pa.get("agent_id") or family
                else:
                    paper_return = 0.0
                    drag = 0.0
                    paper_dd = 0.0
                    closed_trades = 0
                    updates = 0
                    agent_id = family

                ev = record.get("evaluation", {})
                verdict = assess_agent(
                    agent_id=agent_id,
                    research_score=float(ev.get("score") or 0),
                    timeframe_confirmations=int(ev.get("confirmations") or 0),
                    paper_return=paper_return,
                    paper_drawdown=paper_dd,
                    closed_trades=closed_trades,
                    paper_updates=updates,
                    execution_drag_pct=drag,
                )

                rows.append(
                    {
                        "family": family,
                        "agent_id": agent_id,
                        "generation": variant,
                        "research_score": float(ev.get("score") or 0),
                        "timeframe_confirmations": int(ev.get("confirmations") or 0),
                        "paper_return": paper_return,
                        "paper_drawdown": paper_dd,
                        "closed_trades": closed_trades,
                        "paper_updates": updates,
                        "execution_drag_pct": drag,
                        "trust_score": verdict.trust_score,
                        "max_risk_multiplier": verdict.max_risk_multiplier,
                        "action": verdict.action,
                        "reasons": list(verdict.reasons),
                    }
                )

            rows.sort(key=lambda x: x["trust_score"], reverse=True)

            body = {
                "ok": True,
                "mode": "EVIDENCE_BRAIN",
                "can_increase_base_risk": False,
                "can_place_orders": False,
                "can_edit_risk_gates": False,
                "agents": rows,
                "summary": {
                    "agents": len(rows),
                    "paper_eligible": sum(1 for r in rows if r["action"] == "PAPER_ELIGIBLE"),
                    "shadow_only": sum(1 for r in rows if r["action"] == "SHADOW_ONLY"),
                    "probation": sum(1 for r in rows if r["action"] == "PROBATION"),
                    "quarantine": sum(1 for r in rows if r["action"] == "QUARANTINE"),
                },
            }
            status = 200
        except Exception as exc:
            body = {"ok": False, "error": str(exc)[:240], "agents": []}
            status = 502

        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "public, s-maxage=60, stale-while-revalidate=180")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)
