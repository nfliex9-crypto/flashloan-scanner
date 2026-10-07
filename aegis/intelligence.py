from __future__ import annotations

import json
import math
import os
import statistics
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache


SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
FINRA_REG_SHO_URL = "https://api.finra.org/data/group/otcMarket/name/regShoDaily"

WATCHLIST = ("SPY", "QQQ", "NVDA", "TSLA", "AAPL", "MSFT")
KNOWN_CIKS = {
    "SPY": {"cik": "0000884394", "title": "SPDR S&P 500 ETF TRUST"},
    "QQQ": {"cik": "0001067839", "title": "INVESCO QQQ TRUST, SERIES 1"},
    "NVDA": {"cik": "0001045810", "title": "NVIDIA CORP"},
    "TSLA": {"cik": "0001318605", "title": "TESLA, INC."},
    "AAPL": {"cik": "0000320193", "title": "APPLE INC."},
    "MSFT": {"cik": "0000789019", "title": "MICROSOFT CORP"},
}
SEC_USER_AGENT = os.getenv(
    "SEC_USER_AGENT",
    "AEGIS-Agent-City/1.1 https://github.com/nfliex9-crypto/flashloan-scanner",
)


def _request_json(url: str, *, payload: dict | None = None, timeout: int = 12):
    data = None
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "identity",
        "User-Agent": SEC_USER_AGENT,
    }
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


@lru_cache(maxsize=1)
def sec_ticker_map() -> dict[str, dict]:
    raw = _request_json(SEC_TICKERS_URL)
    out: dict[str, dict] = {}
    for row in raw.values():
        ticker = str(row.get("ticker", "")).upper().strip()
        if not ticker:
            continue
        out[ticker] = {
            "cik": str(row["cik_str"]).zfill(10),
            "title": row.get("title", ticker),
        }
    return out


def _days_ago(value: str, today: date | None = None) -> int | None:
    try:
        d = date.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    today = today or datetime.now(timezone.utc).date()
    return (today - d).days


def _columnar_rows(recent: dict) -> list[dict]:
    if not recent:
        return []
    keys = list(recent.keys())
    length = max((len(recent.get(k, [])) for k in keys), default=0)
    rows = []
    for i in range(length):
        row = {}
        for key in keys:
            values = recent.get(key, [])
            row[key] = values[i] if i < len(values) else None
        rows.append(row)
    return rows


def score_sec_activity(filings: list[dict]) -> dict:
    """Attention score only. It does not infer bullish/bearish direction."""
    counts = {"form4_7d": 0, "form4_30d": 0, "8k_30d": 0, "major_90d": 0}
    latest = []

    for row in filings:
        form = str(row.get("form") or "")
        filed = str(row.get("filingDate") or "")
        age = _days_ago(filed)
        if age is None or age < 0:
            continue

        if form in {"4", "4/A"}:
            if age <= 7:
                counts["form4_7d"] += 1
            if age <= 30:
                counts["form4_30d"] += 1
        if form in {"8-K", "8-K/A"} and age <= 30:
            counts["8k_30d"] += 1
        if form in {"10-Q", "10-Q/A", "10-K", "10-K/A", "8-K", "8-K/A"} and age <= 90:
            counts["major_90d"] += 1

        if len(latest) < 6:
            latest.append(
                {
                    "form": form,
                    "filing_date": filed,
                    "accession": row.get("accessionNumber"),
                    "primary_document": row.get("primaryDocument"),
                }
            )

    # This is an information-attention score, not a trade direction score.
    score = 18.0
    score += min(34.0, counts["form4_7d"] * 8.0 + counts["form4_30d"] * 2.0)
    score += min(24.0, counts["8k_30d"] * 6.0)
    score += min(24.0, counts["major_90d"] * 2.5)
    score = round(max(0.0, min(100.0, score)), 1)

    return {
        "attention_score": score,
        "counts": counts,
        "latest_filings": latest,
        "direction": "UNKNOWN",
        "role": "CONTEXT_ONLY",
        "note": "SEC activity measures filing intensity. Form 4 count alone does not reveal buy/sell direction.",
    }


def sec_snapshot(symbol: str) -> dict:
    mapping = KNOWN_CIKS.get(symbol.upper()) or sec_ticker_map().get(symbol.upper())
    if not mapping:
        return {
            "ok": False,
            "symbol": symbol,
            "source": "SEC EDGAR",
            "error": "Ticker not found in SEC ticker map",
        }

    payload = _request_json(SEC_SUBMISSIONS_URL.format(cik=mapping["cik"]))
    recent = payload.get("filings", {}).get("recent", {})
    rows = _columnar_rows(recent)
    activity = score_sec_activity(rows)

    return {
        "ok": True,
        "symbol": symbol,
        "source": "SEC EDGAR",
        "company": mapping["title"],
        "cik": mapping["cik"],
        **activity,
    }


def aggregate_finra_rows(rows: list[dict]) -> dict:
    by_date: dict[str, dict[str, float]] = defaultdict(
        lambda: {"total": 0.0, "short": 0.0, "short_exempt": 0.0}
    )
    for row in rows:
        d = str(row.get("tradeReportDate") or "")
        if not d:
            continue
        try:
            by_date[d]["total"] += float(row.get("totalParQuantity") or 0)
            by_date[d]["short"] += float(row.get("shortParQuantity") or 0)
            by_date[d]["short_exempt"] += float(row.get("shortExemptParQuantity") or 0)
        except (TypeError, ValueError):
            continue

    dates = sorted(by_date)
    series = []
    for d in dates:
        bucket = by_date[d]
        total = bucket["total"]
        ratio = bucket["short"] / total if total > 0 else 0.0
        exempt_ratio = bucket["short_exempt"] / total if total > 0 else 0.0
        series.append(
            {
                "date": d,
                "total_volume": total,
                "short_volume": bucket["short"],
                "short_exempt_volume": bucket["short_exempt"],
                "short_volume_ratio": ratio,
                "short_exempt_ratio": exempt_ratio,
            }
        )

    if not series:
        return {
            "latest": None,
            "data_age_days": None,
            "context_eligible": False,
            "avg_5d_ratio": 0.0,
            "zscore_20d": 0.0,
            "anomaly_score": 0.0,
            "history": [],
        }

    ratios = [x["short_volume_ratio"] for x in series[-20:]]
    latest_ratio = ratios[-1]
    avg5 = statistics.fmean(ratios[-5:])
    if len(ratios) >= 5 and statistics.pstdev(ratios) > 1e-12:
        z = (latest_ratio - statistics.fmean(ratios)) / statistics.pstdev(ratios)
    else:
        z = 0.0

    # Anomaly/intensity only. FINRA short-sale volume is not the same as short interest.
    anomaly = min(100.0, 15.0 + abs(z) * 22.0 + abs(latest_ratio - avg5) * 120.0)

    latest_age = _days_ago(series[-1]["date"])
    context_eligible = latest_age is not None and 0 <= latest_age <= 10

    return {
        "latest": series[-1],
        "data_age_days": latest_age,
        "context_eligible": context_eligible,
        "avg_5d_ratio": avg5,
        "zscore_20d": z,
        "anomaly_score": round(anomaly, 1),
        "history": series[-10:],
    }


def finra_snapshot(symbol: str) -> dict:
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=75)
    body = {
        "limit": 1000,
        "fields": [
            "tradeReportDate",
            "securitiesInformationProcessorSymbolIdentifier",
            "shortParQuantity",
            "shortExemptParQuantity",
            "totalParQuantity",
            "reportingFacilityCode",
        ],
        "compareFilters": [
            {
                "compareType": "equal",
                "fieldName": "securitiesInformationProcessorSymbolIdentifier",
                "fieldValue": symbol.upper(),
            }
        ],
        "dateRangeFilters": [
            {
                "fieldName": "tradeReportDate",
                "startDate": start.isoformat(),
                "endDate": today.isoformat(),
            }
        ],
    }
    rows = _request_json(FINRA_REG_SHO_URL, payload=body)
    agg = aggregate_finra_rows(rows if isinstance(rows, list) else [])

    return {
        "ok": True,
        "symbol": symbol,
        "source": "FINRA Reg SHO Daily Short Sale Volume",
        **agg,
        "direction": "NEUTRAL_CONTEXT",
        "role": "CONTEXT_ONLY",
        "note": "Short-sale volume is not short interest and is not treated as a bearish signal.",
    }


def build_symbol_intelligence(symbol: str) -> dict:
    errors: list[str] = []

    try:
        sec = sec_snapshot(symbol)
        if not sec.get("ok"):
            errors.append(f"SEC: {sec.get('error', 'unavailable')}")
    except Exception as exc:
        sec = {
            "ok": False,
            "symbol": symbol,
            "source": "SEC EDGAR",
            "error": str(exc),
        }
        errors.append(f"SEC: {exc}")

    try:
        finra = finra_snapshot(symbol)
    except Exception as exc:
        finra = {
            "ok": False,
            "symbol": symbol,
            "source": "FINRA Reg SHO Daily Short Sale Volume",
            "error": str(exc),
        }
        errors.append(f"FINRA: {exc}")

    sec_score = float(sec.get("attention_score", 0.0)) if sec.get("ok") else 0.0
    finra_usable = bool(finra.get("ok") and finra.get("context_eligible"))
    finra_score = float(finra.get("anomaly_score", 0.0)) if finra_usable else 0.0

    available = int(bool(sec.get("ok"))) + int(finra_usable)
    if sec.get("ok") and finra_usable:
        attention = 0.55 * sec_score + 0.45 * finra_score
    elif sec.get("ok"):
        attention = sec_score
    elif finra_usable:
        attention = finra_score
    else:
        attention = 0.0

    return {
        "symbol": symbol,
        "attention_score": round(attention, 1),
        "execution_eligible": False,
        "role": "CONTEXT_ONLY",
        "sources_available": available,
        "finra_fresh": finra_usable,
        "sec": sec,
        "finra": finra,
        "errors": errors,
    }


def build_intelligence_hq(symbols: tuple[str, ...] = WATCHLIST) -> dict:
    assets = [build_symbol_intelligence(symbol) for symbol in symbols]
    assets.sort(key=lambda x: x["attention_score"], reverse=True)

    return {
        "ok": True,
        "engine": "AEGIS Intelligence HQ v1",
        "mode": "FREE_PUBLIC_DATA_CONTEXT",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "watchlist": list(symbols),
        "assets": assets,
        "sources": {
            "sec": {
                "name": "SEC EDGAR",
                "auth": "NO_API_KEY",
                "purpose": "Company submissions and filing activity",
            },
            "finra": {
                "name": "FINRA Reg SHO Daily Short Sale Volume",
                "auth": "PUBLIC_DATASET",
                "purpose": "Short-sale flow intensity/anomaly context",
            },
        },
        "rules": [
            "Alternative data cannot place or size a trade by itself.",
            "SEC Form 4 count is activity, not buy/sell direction until transaction XML is parsed.",
            "FINRA short-sale volume is not short interest and is never treated as a standalone bearish signal.",
            "Every future persisted event must keep source timestamp and ingestion timestamp to block look-ahead bias.",
        ],
        "next_stage": {
            "name": "Persistent Intelligence Ledger",
            "requires": "Neon DATABASE_URL + idempotent event keys",
            "then": "Parse Form 4 transaction XML, persist event-time data, and measure incremental strategy lift.",
        },
    }
