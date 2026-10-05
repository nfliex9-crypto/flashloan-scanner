from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler

RUNS_URL = (
    "https://api.github.com/repos/"
    "nfliex9-crypto/flashloan-scanner/actions/runs"
    "?branch=Bot&per_page=40"
)

WORKFLOWS = (
    "AEGIS CI",
    "AEGIS Live Verification",
    "AEGIS Evolution Lab",
    "AEGIS Forward Paper Trading",
    "Python checks",
)


def normalize_run(run: dict) -> dict:
    return {
        "id": run.get("id"),
        "name": run.get("name"),
        "status": run.get("status"),
        "conclusion": run.get("conclusion"),
        "title": run.get("display_title"),
        "sha": (run.get("head_sha") or "")[:8],
        "created_at": run.get("created_at"),
        "updated_at": run.get("updated_at"),
        "html_url": run.get("html_url"),
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            request = urllib.request.Request(
                RUNS_URL,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "AEGIS-Test-Monitor/1.0",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            with urllib.request.urlopen(request, timeout=8) as response:
                payload = json.loads(response.read().decode("utf-8"))

            runs = payload.get("workflow_runs", [])
            latest = {}
            for run in runs:
                name = run.get("name")
                if name in WORKFLOWS and name not in latest:
                    latest[name] = normalize_run(run)

            ordered = [latest[name] for name in WORKFLOWS if name in latest]

            body = {
                "ok": True,
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "runs": ordered,
                "passing": sum(1 for run in ordered if run.get("conclusion") == "success"),
                "running": sum(1 for run in ordered if run.get("status") != "completed"),
                "failing": sum(
                    1
                    for run in ordered
                    if run.get("status") == "completed"
                    and run.get("conclusion") not in ("success", "skipped")
                ),
            }
        except Exception as exc:
            body = {"ok": False, "error": str(exc)[:220], "runs": []}

        output = json.dumps(body).encode("utf-8")
        self.send_response(200 if body.get("ok") else 502)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "public, s-maxage=30, stale-while-revalidate=90")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(output)
