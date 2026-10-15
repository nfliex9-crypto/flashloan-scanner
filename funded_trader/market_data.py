"""ProjectX/TopstepX market-data-only adapter and auditable bar storage.

NO order endpoint exists here. Run on a permitted local machine.
All credentials come from environment variables, never the UI or repository.
"""
from __future__ import annotations
import csv
import hashlib
import io
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

class FeedError(RuntimeError):
    pass

def timestamp_utc(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Timestamp must be ISO-8601 string")
    date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if date.tzinfo is None:
        raise ValueError("Naive timestamps are prohibited")
    return date.astimezone(timezone.utc)

def money(value) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Invalid numeric market value") from exc
    if not result.is_finite():
        raise ValueError("Non-finite market value")
    return result

@dataclass(frozen=True)
class Bar:
    time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    def __post_init__(self):
        if self.time.tzinfo is None or self.time.utcoffset() != timezone.utc.utcoffset(self.time):
            raise ValueError("Bar timestamps must be UTC and timezone-aware")
        values = (self.open, self.high, self.low, self.close, self.volume)
        if any(not x.is_finite() for x in values):
            raise ValueError("Non-finite bar")
        if self.low <= 0 or self.volume < 0 or self.high < max(self.open, self.close, self.low) or self.low > min(self.open, self.close):
            raise ValueError("Impossible OHLCV bar")

def parse_projectx_bars(rows: list[dict]) -> list[Bar]:
    if not isinstance(rows, list):
        raise ValueError("Bars must be a list")
    bars = []
    for item in rows:
        if not isinstance(item, dict):
            raise ValueError("Invalid bar payload")
        bars.append(Bar(timestamp_utc(item["t"]), money(item["o"]),
                        money(item["h"]), money(item["l"]),
                        money(item["c"]), money(item["v"])))
    bars.sort(key=lambda b: b.time)
    if len({b.time for b in bars}) != len(bars):
        raise ValueError("Duplicate bar timestamps are prohibited")
    return bars

def csv_bytes(bars: list[Bar]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(("timestamp_utc", "open", "high", "low", "close", "volume"))
    for b in bars:
        writer.writerow((b.time.isoformat(), str(b.open), str(b.high), str(b.low), str(b.close), str(b.volume)))
    return output.getvalue().encode("utf-8")

def read_bars_csv(path: str | Path) -> list[Bar]:
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        expected = {"timestamp_utc", "open", "high", "low", "close", "volume"}
        if not expected.issubset(reader.fieldnames or []):
            raise ValueError("Missing required CSV header")
        bars = [Bar(timestamp_utc(row["timestamp_utc"]), money(row["open"]),
                    money(row["high"]), money(row["low"]), money(row["close"]),
                    money(row["volume"])) for row in reader]
    if not bars:
        raise ValueError("Empty dataset")
    if any(b.time >= bars[i+1].time for i,b in enumerate(bars[:-1])):
        raise ValueError("CSV must contain strictly increasing UTC timestamps")
    return bars

def store_bars(path: str | Path, bars: list[Bar], *, contract_id: str, source: str, interval_minutes: int):
    if not bars or not contract_id or not source or interval_minutes < 1:
        raise ValueError("Missing provenance or empty data")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = csv_bytes(bars)
    path.write_bytes(raw)
    meta = {"source": source, "contract_id": contract_id, "interval_minutes": interval_minutes,
            "row_count": len(bars), "first_utc": bars[0].time.isoformat(),
            "last_utc": bars[-1].time.isoformat(), "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "note": "Provenance describes API response, not independently verified exchange truth."}
    path.with_suffix(path.suffix + ".provenance.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta

class ProjectXReadOnly:
    BASE = "https://api.topstepx.com"
    PERMITTED = frozenset(("/api/Auth/loginKey", "/api/Contract/search", "/api/History/retrieveBars"))

    def __init__(self, username: str, api_key: str, timeout: float = 15):
        if not username.strip() or not api_key.strip() or not 0 < timeout <= 60:
            raise ValueError("ProjectX username/key and valid timeout required")
        self.username = username
        self._api_key = api_key
        self.timeout = timeout
        self._token: str | None = None

    @classmethod
    def from_environment(cls):
        return cls(os.environ.get("PROJECTX_USERNAME", ""), os.environ.get("PROJECTX_API_KEY", ""))

    def _post(self, route: str, data: dict, *, token_required: bool = True) -> dict:
        if route not in self.PERMITTED:
            raise FeedError("Only documented read-only endpoints are permitted")
        if token_required and not self._token:
            raise FeedError("Authenticate first")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if token_required:
            headers["Authorization"] = "Bearer " + self._token
        request = Request(self.BASE + route, data=json.dumps(data).encode("utf-8"),
                          headers=headers, method="POST")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            # Never copy HTTP error bodies: providers can echo sensitive secrets.
            raise FeedError("Provider request failed; verify access/subscription and connectivity") from None
        if not isinstance(payload, dict) or payload.get("success") is not True:
            code = payload.get("errorCode") if isinstance(payload, dict) else "unknown"
            raise FeedError("Provider rejected request (error code: " + str(code)[:12] + ")")
        return payload

    def authenticate(self) -> None:
        result = self._post("/api/Auth/loginKey",
                            {"userName": self.username, "apiKey": self._api_key},
                            token_required=False)
        token = result.get("token")
        if not isinstance(token, str) or not token:
            raise FeedError("Provider response missing authentication token")
        self._token = token

    def search_contracts(self, text: str) -> list[dict]:
        if not 1 <= len(text.strip()) <= 30:
            raise ValueError("Invalid contract search")
        payload = self._post("/api/Contract/search", {"searchText": text, "live": False})
        contracts = payload.get("contracts")
        if not isinstance(contracts, list):
            raise FeedError("Missing contracts")
        return contracts

    def retrieve_bars(self, contract_id: str, start: datetime, end: datetime,
                      minutes: int = 5, limit: int = 20000) -> list[Bar]:
        if not contract_id.startswith("CON.") or not (1 <= minutes <= 60) or not (1 <= limit <= 20000):
            raise ValueError("Contract, interval or limit invalid")
        if start.tzinfo is None or end.tzinfo is None or end <= start:
            raise ValueError("Start/end must be ordered timezone-aware timestamps")
        payload = self._post("/api/History/retrieveBars", {
            "contractId": contract_id, "live": False,
            "startTime": start.astimezone(timezone.utc).isoformat(),
            "endTime": end.astimezone(timezone.utc).isoformat(),
            "unit": 2, "unitNumber": minutes, "limit": limit,
            "includePartialBar": False})
        bars = parse_projectx_bars(payload.get("bars"))
        if bars and (bars[0].time < start.astimezone(timezone.utc) or bars[-1].time > end.astimezone(timezone.utc)):
            raise FeedError("Provider returned bars outside requested range")
        return bars
