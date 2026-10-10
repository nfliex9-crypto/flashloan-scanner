"""Optional external research critic. GROK NEVER AUTHORISES ANY TRADE.

Runs only on explicit owner-signed requests, on bounded sanitized Neon
operational receipts. No broker credentials, wallet IDs, chat prompts, data
exports or customer positions leave AEGIS. An LLM response is commentary,
never verified market evidence or an execution signal.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

XAI_ENDPOINT = "https://api.x.ai/v1/responses"
MODEL_ALLOWLIST = frozenset(("grok-4.3", "grok-4.7"))
MAX_REQUEST = 6_000
MAX_OUTPUT_TOKENS = 256
MAX_RESPONSE_BYTES = 24_000


class AdvisoryUnavailable(Exception):
    pass


def provider_status() -> dict:
    return {
        "ok": True,
        "grok": {
            "state": "OWNER_ENABLED" if bool(os.getenv("XAI_API_KEY")) else "NOT_CONFIGURED",
            "mode": "MANUAL_READ_ONLY_CRITIC",
            "external_spend_possible": bool(os.getenv("XAI_API_KEY")),
            "automatic_calls": False,
        },
        "jev": {
            "state": "SEPARATE_RAILWAY_SERVICE",
            "mode": "NO_ACCOUNT_OR_WALLET_BRIDGE",
            "notes": "Jev on Hyperliquid has separate order execution; never infer its runtime status from a repository link.",
        },
        "fincept": {
            "state": "ARCHITECTURE_REFERENCE_ONLY",
            "license": "AGPL-3.0-or-later",
            "code_vendored": False,
        },
        "vibe_trading": {
            "state": "EVIDENCE_AND_CANARY_PATTERNS_ADOPTED",
            "runtime_dependency": False,
        },
        "execution_authorized": False,
    }


def sanitized_receipts(diagnostic: dict) -> dict:
    """Allow only fixed categorical values, counts and interval IDs, not JSON passthrough."""
    if diagnostic.get("ok") is not True or diagnostic.get("database", {}).get("state") != "CONNECTED":
        raise AdvisoryUnavailable("neon_source_not_verified")
    kraken = diagnostic.get("kraken_paper") or {}
    healthy = kraken.get("healthy_intervals_minutes")
    if not isinstance(healthy, list):
        raise AdvisoryUnavailable("kraken_health_not_verified")
    approved = [x for x in healthy if type(x) is int and x in (1, 5, 15, 60, 240, 1440, 10080)]
    approved = list(dict.fromkeys(approved))
    if not approved:
        raise AdvisoryUnavailable("no_fresh_kraken_data")
    permitted = {
        "database": {"CONNECTED"},
        "market_monitor": {"CURRENT", "STALE", "NO_EVIDENCE", "SCHEMA_MISSING", "READ_FAILED"},
        "hourly_forward": {"CURRENT", "STALE", "NO_EVIDENCE", "SCHEMA_MISSING", "READ_FAILED"},
        "mt5_demo": {"CURRENT", "STALE", "NO_EVIDENCE", "SCHEMA_MISSING", "READ_FAILED"},
    }
    def state(key: str) -> str:
        val = (diagnostic.get(key) or {}).get("state")
        return val if val in permitted[key] else "UNKNOWN"
    return {
        "timestamp": str(diagnostic.get("checked_at") or "")[:32],
        "data_source": "verified Neon canaries (not trade signals)",
        "database": state("database"),
        "market_monitor": state("market_monitor"),
        "hourly_forward": state("hourly_forward"),
        "mt5_demo": state("mt5_demo"),
        "kraken_healthy_intervals_minutes": approved,
        "kraken_expected_intervals_minutes": [1, 5, 15, 60, 240, 1440, 10080],
        "trade_count_provenance": "not supplied; never infer orders or profits",
        "broker_execution_enabled": False,
    }


def parse_review_reply(payload: dict) -> str:
    if payload.get("status") != "completed":
        raise AdvisoryUnavailable("incomplete_grok_reply")
    parts = []
    for item in payload.get("output", []):
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for piece in item.get("content", []):
            if isinstance(piece, dict) and piece.get("type") == "output_text":
                v = piece.get("text")
                if isinstance(v, str):
                    parts.append(v)
    result = "\n".join(parts).strip()
    if not result:
        raise AdvisoryUnavailable("empty_grok_reply")
    return result[:2400]


def request_grok_critique(evidence: dict, *, key: str | None = None,
                         model: str | None = None) -> dict:
    key = key if key is not None else os.getenv("XAI_API_KEY", "")
    if len(key) < 20:
        raise AdvisoryUnavailable("grok_not_configured")
    model = model or os.getenv("AEGIS_GROK_REVIEW_MODEL", "grok-4.3")
    if model not in MODEL_ALLOWLIST:
        raise AdvisoryUnavailable("grok_model_not_allowed")
    validated = sanitized_receipts(evidence)
    content = (
        "You are an independent operational risk auditor, NOT a trading agent. "
        "Assess the following AEGIS diagnostics; identify stale/missing evidence "
        "and limitations. No price forecasts, trading signals, portfolio sizing, "
        "broker instructions or profit claims. Never claim data is live without "
        "current source-backed evidence. Use 3 concise Arabic sentences. "
        "These receipts have no executable authority: " +
        json.dumps(validated, separators=(",", ":"), ensure_ascii=False)
    )
    body = json.dumps({
        "model": model,
        "input": content,
        "store": False,
        "tools": [],
        "tool_choice": "none",
        "max_output_tokens": MAX_OUTPUT_TOKENS,
    }, separators=(",", ":")).encode("utf-8")
    if len(body) > MAX_REQUEST:
        raise AdvisoryUnavailable("review_payload_too_large")
    req = urllib.request.Request(
        XAI_ENDPOINT, method="POST", data=body,
        headers={"Authorization": "Bearer " + key,
                 "Content-Type": "application/json",
                 "User-Agent": "AEGIS-PAPER-RISK-REVIEW/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=14) as res:
            raw = res.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise AdvisoryUnavailable("grok_response_too_large")
            answer = json.loads(raw)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError,
            ValueError, UnicodeDecodeError) as exc:
        # NEVER return upstream exception text: includes URLs and account info.
        raise AdvisoryUnavailable("grok_provider_unavailable") from None
    return {
        "ok": True,
        "model": model,
        "text": parse_review_reply(answer),
        "source": "validated read-only Neon operations diagnostics",
        "external_spend_possible": True,
        "automatic_execution": False,
        "live_execution_enabled": False,
        "demo_order_execution_enabled": False,
    }


def owner_review() -> tuple[int, dict]:
    if not os.getenv("XAI_API_KEY"):
        return 503, {"ok": False, "error": "grok_not_configured"}
    from .ops_health import diagnose
    evidence = diagnose()
    try:
        return 200, request_grok_critique(evidence)
    except AdvisoryUnavailable as exc:
        return 503, {"ok": False, "error": str(exc)}
    except Exception:
        return 503, {"ok": False, "error": "grok_review_unavailable"}
