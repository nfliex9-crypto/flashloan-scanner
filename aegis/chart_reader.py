"""Source-attributed chart observations. Analysis only; no order capability.

The mutable current bar is kept separate from closed-bar analysis. Reading a
chart now does not prove that the vendor's quote is real-time.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import re
from datetime import datetime, timezone

INTERVALS = (5, 15, 60, 240)
SOURCES = {"KRAKEN_WS", "TRADINGVIEW_DESKTOP", "TWELVE_DATA_REST"}
MAX_IMAGE_BYTES = 700_000


def utcnow():
    return datetime.now(timezone.utc)


def stamp(value):
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamp_requires_timezone")
    return dt.astimezone(timezone.utc)


def number(value, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("numeric_value_required")
    if not math.isfinite(value) or (positive and value <= 0):
        raise ValueError("invalid_number")
    return float(value)


def instrument(symbol):
    if symbol in ("KRAKEN:BTCUSD", "KRAKEN:ETHUSD"):
        return "CRYPTO_SPOT"
    if re.fullmatch(r"[A-Z0-9_]{2,24}:XAUUSD", symbol):
        return "GOLD_SPOT_REFERENCE"
    if re.fullmatch(r"COMEX:(MGC|GC)([FGHJKMNQUVXZ][0-9]{4}|1!)", symbol):
        return "GOLD_FUTURES"
    raise ValueError("unsupported_chart_symbol")


def image_png(encoded):
    """Decode/re-encode bounded PNGs; discard metadata and reject huge images."""
    if not isinstance(encoded, str) or len(encoded) > MAX_IMAGE_BYTES * 4 // 3 + 8:
        raise ValueError("chart_image_too_large")
    raw = base64.b64decode(encoded, validate=True)
    if len(raw) > MAX_IMAGE_BYTES or not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("chart_image_must_be_png")
    from PIL import Image
    with Image.open(io.BytesIO(raw)) as im:
        if not (200 <= im.width <= 4000 and 100 <= im.height <= 2500):
            raise ValueError("invalid_chart_image_dimensions")
        im.load()
        im.thumbnail((1280, 800))
        out = io.BytesIO()
        im.convert("RGB").save(out, format="PNG")
    data = out.getvalue()
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("chart_image_too_large")
    return base64.b64encode(data).decode(), hashlib.sha256(data).hexdigest()


def normalize(payload, *, now=None, allowed_source=None):
    now = now or utcnow()
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError("unsupported_chart_payload")
    source = payload.get("source")
    if source not in SOURCES or (allowed_source and source != allowed_source):
        raise ValueError("invalid_chart_source")
    symbol = payload.get("symbol", "")
    kind = instrument(symbol)
    if source == "KRAKEN_WS" and not symbol.startswith("KRAKEN:"):
        raise ValueError("source_symbol_mismatch")
    if source == "TWELVE_DATA_REST" and symbol != "TWELVEDATA:XAUUSD":
        raise ValueError("source_symbol_mismatch")
    interval = payload.get("interval_minutes")
    if type(interval) is not int or interval not in INTERVALS:
        raise ValueError("chart_interval_must_be_5m_or_higher")
    observed = stamp(payload.get("observed_at"))
    if not -5 <= (now - observed).total_seconds() <= 120:
        raise ValueError("stale_capture_timestamp")
    if source == "TRADINGVIEW_DESKTOP":
        if payload.get("replay") is not False:
            raise ValueError("replay_must_be_verified_off")
        if payload.get("chart_type") not in (0, 1, 9):
            raise ValueError("standard_ohlc_chart_required")
        if payload.get("chart_only") is not True:
            raise ValueError("chart_only_capture_required")
    raw = payload.get("bars")
    if not isinstance(raw, list) or not 55 <= len(raw) <= 300:
        raise ValueError("require_55_to_300_bars")
    bars = []
    previous = None
    for row in raw:
        if not isinstance(row, dict):
            raise ValueError("invalid_bar")
        ts = row.get("time")
        if type(ts) is not int or ts < 946684800 or ts > observed.timestamp() + 5:
            raise ValueError("invalid_bar_timestamp")
        if previous is not None and ts <= previous:
            raise ValueError("duplicate_or_unordered_bars")
        previous = ts
        o, h, l, c = [number(row.get(k), positive=True) for k in ("open", "high", "low", "close")]
        if not l <= min(o, c) <= max(o, c) <= h:
            raise ValueError("inconsistent_ohlc")
        volume = row.get("volume")
        if volume is not None:
            volume = number(volume)
            if volume < 0:
                raise ValueError("negative_volume")
        bars.append(dict(time=ts, open=o, high=h, low=l, close=c, volume=volume))
    # Never accept data-window strings, Pine code, arbitrary account data, or URLs.
    studies = []
    for study in payload.get("studies", [])[:20]:
        if not isinstance(study, dict):
            continue
        name = str(study.get("name", ""))[:60]
        values = {str(k)[:40]: number(v) for k, v in list(study.get("values", {}).items())[:12]
                  if isinstance(v, (float, int)) and not isinstance(v, bool) and math.isfinite(v)}
        if name and values:
            studies.append({"name": name, "values": values})
    doc = {"version": 1, "source": source, "symbol": symbol, "instrument_kind": kind,
           "interval_minutes": interval, "observed_at": observed.isoformat(),
           "bars": bars, "studies": studies, "execution_enabled": False,
           "quote_semantics": "CHART_OHLC_NOT_EXECUTABLE_BID_ASK",
           "delay_status": "PUBLIC_WS" if source == "KRAKEN_WS" else "VENDOR_DELAY_UNVERIFIED"}
    doc["source_id"] = f"{source}:{symbol}:{interval}"
    doc["analysis"] = analyze(doc, now=observed)
    doc["snapshot_id"] = hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()
    if payload.get("image_png") is not None:
        if source != "TRADINGVIEW_DESKTOP":
            raise ValueError("image_only_from_chart_bridge")
        encoded, image_hash = image_png(payload["image_png"])
        # Retain an image with ITS numerical context, even when newer ticks arrive.
        doc["last_image"] = {"image_png":encoded,"image_sha256":image_hash,
                             "image_kind":"TRADINGVIEW_CHART_CROP","context":dict(doc)}
    return doc


def ema(values, n):
    result = values[0]
    for x in values[1:]:
        result += 2 / (n + 1) * (x - result)
    return result


def analyze(doc, *, now=None):
    """Deterministic observers consume one shared snapshot; no invented confidence."""
    now = now or utcnow()
    seconds = doc["interval_minutes"] * 60
    bars = [b for b in doc["bars"] if b["time"] + seconds <= now.timestamp()]
    if len(bars) < 50:
        return {"state": "WARMING_UP", "observers": []}
    closes = [b["close"] for b in bars]
    fast, slow = ema(closes, 20), ema(closes, 50)
    diffs = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gain = sum(max(d, 0) for d in diffs[:14]) / 14
    loss = sum(max(-d, 0) for d in diffs[:14]) / 14
    for d in diffs[14:]:
        gain, loss = (gain * 13 + max(d, 0)) / 14, (loss * 13 + max(-d, 0)) / 14
    rsi = 50 if gain == loss == 0 else 100 if loss == 0 else 100 - 100 / (1 + gain / loss)
    ranges = [max(b["high"] - b["low"], abs(b["high"] - bars[i-1]["close"]),
                  abs(b["low"] - bars[i-1]["close"])) for i, b in enumerate(bars) if i]
    atr = sum(ranges[:14]) / 14
    for tr in ranges[14:]:
        atr = (atr * 13 + tr) / 14
    # Exclude the evaluated bar from the breakout channel.
    channel = bars[-21:-1]
    support, resistance = min(b["low"] for b in channel), max(b["high"] for b in channel)
    latest = bars[-1]
    trend = "BULLISH" if closes[-1] > fast > slow else "BEARISH" if closes[-1] < fast < slow else "MIXED"
    momentum = "BULLISH" if rsi > 55 else "BEARISH" if rsi < 45 else "NEUTRAL"
    breakout = "ABOVE_RANGE" if closes[-1] > resistance else "BELOW_RANGE" if closes[-1] < support else "IN_RANGE"
    gaps = sum(bars[i]["time"] - bars[i-1]["time"] != seconds for i in range(1, len(bars)))
    return {"state": "READY", "basis": "CLOSED_CANDLES", "bar_time": latest["time"],
            "ema20": fast, "ema50": slow, "rsi14": rsi, "atr14": atr,
            "support20": support, "resistance20": resistance,
            "gap_count": gaps, "bar_count": len(bars), "execution_enabled": False,
            "observers": [
                {"id": "trend", "state": trend, "inputs": ["close", "ema20", "ema50"]},
                {"id": "momentum", "state": momentum, "inputs": ["rsi14"]},
                {"id": "structure", "state": breakout, "inputs": ["support20", "resistance20", "close"]}],
            "forming_bar": doc["bars"][-1] if doc["bars"][-1]["time"] + seconds > now.timestamp() else None}


def freshness(doc, *, now=None):
    now = now or utcnow()
    age = (now - stamp(doc["observed_at"])).total_seconds()
    bar_age = now.timestamp() - doc["bars"][-1]["time"]
    if age < -5 or bar_age < -5:
        state = "CLOCK_MISMATCH"
    elif age > 90:
        state = "DISCONNECTED"
    elif bar_age > doc["interval_minutes"] * 60 + 120:
        state = "STALE_MARKET_DATA"
    elif doc["source"] != "KRAKEN_WS":
        state = "OBSERVED_DELAY_UNVERIFIED"
    else:
        state = "STREAMING"
    return {"state": state, "capture_age_seconds": round(age, 1),
            "last_bar_age_seconds": round(bar_age, 1),
            "analysis_usable": state in ("STREAMING", "OBSERVED_DELAY_UNVERIFIED"),
            "execution_enabled": False}


def render_png(doc):
    """Render only source bars, never a fabricated TradingView screenshot."""
    from PIL import Image, ImageDraw
    bars = doc["bars"][-80:]
    im = Image.new("RGB", (1200, 660), "#091420")
    draw = ImageDraw.Draw(im)
    hi, lo = max(b["high"] for b in bars), min(b["low"] for b in bars)
    span = hi - lo or hi * .001
    y = lambda p: 565 - (p - lo) / span * 470
    draw.text((30, 20), f"{doc['symbol']}  {doc['interval_minutes']}m  |  {doc['source']}", fill="white")
    draw.text((30, 42), f"Observed {doc['observed_at']} | market OHLC, not broker execution", fill="#a4b8c9")
    for i in range(6):
        p = lo + span * i / 5
        draw.line((30, y(p), 1080, y(p)), fill="#213246")
        draw.text((1090, y(p)), f"{p:,.2f}", fill="#a4b8c9")
    for i, b in enumerate(bars):
        x = 40 + i * 1030 / len(bars)
        color = "#36d7a3" if b["close"] >= b["open"] else "#ee647a"
        draw.line((x, y(b["low"]), x, y(b["high"])), fill=color, width=2)
        a, z = sorted((y(b["open"]), y(b["close"])))
        draw.rectangle((x-4, a, x+4, max(a+1, z)), fill=color)
    draw.text((30, 605), datetime.fromtimestamp(bars[0]["time"], timezone.utc).isoformat(), fill="#a4b8c9")
    draw.text((780, 605), datetime.fromtimestamp(bars[-1]["time"], timezone.utc).isoformat(), fill="#a4b8c9")
    out = io.BytesIO()
    im.save(out, format="PNG")
    return base64.b64encode(out.getvalue()).decode()
