# AEGIS chart reader — numbers and images

Upstream reviewed: [tradesdontlie/tradingview-mcp](https://github.com/tradesdontlie/tradingview-mcp),
MIT, revision `c05b8f5755ed8e64ea242de88ddbf46aa24d56a4`.
This is a companion importing the original project's read functions, not a fork
claiming authorship. Upstream is not an official TradingView API. Its private
Electron paths can break after a Desktop update. No upstream source is vendored.

## What actually runs

* Railway: Kraken WebSocket updates → bounded queue → numeric observers → Neon.
  Latest snapshots are persisted at most every five seconds per symbol/timeframe.
  Existing paper execution still waits for closed candles; this reader places no orders.
* Vercel: authenticated chart API, chart dashboard, optional image+numeric model
  comparison through AI Gateway using the deployment's OIDC identity.
* Laptop: existing, signed-in TradingView Desktop → read-only upstream functions
  → OHLC and numeric indicator values → chart-only image once/minute → signed HTTPS
  to AEGIS. Only the currently selected chart is sampled. Keep the app open.

Gold REST is explicitly a once/minute Twelve Data fallback using the existing
key, with unknown vendor delay. GC/MGC futures stay separate from spot XAUUSD.
Opening the gold tab during a closed market does not create a live quote.

## Laptop setup (prepared; requires the owner's local action)

The owner originally excluded Windows. Their available laptop is Windows;
Windows startup is **not performed remotely**. These same companion files also
run on Mac/Linux. Enable local Desktop access only on the owner's chosen system.

Install Node.js 22+ and Git from their official distributions if missing. Clone
both repos to user-owned folders, then pin the reviewed upstream:

```sh
git clone https://github.com/tradesdontlie/tradingview-mcp.git
cd tradingview-mcp
git checkout c05b8f5755ed8e64ea242de88ddbf46aa24d56a4
npm ci --ignore-scripts
cd ..
git clone --single-branch --branch agent-city-v1 https://github.com/nfliex9-crypto/flashloan-scanner.git
```

Close and start **your installed TradingView Desktop** with
`--remote-debugging-port=9222 --remote-debugging-address=127.0.0.1`.
Use the installation's actual executable; do not use a package-copy workaround
or expose port 9222 to the network. If the installation disallows debugging,
stop and use the cloud data reader until a supported installation is available.
Log in yourself, open standard candles, turn Bar Replay off and select 5m/15m/1h/4h.

Run `python flashloan-scanner/integrations/tradingview/start.py`. It prompts locally
for the upstream directory, the AEGIS chart token and, only if Deployment
Protection requires it, the existing Vercel automation credential. Password
prompts are hidden. Tokens stay in that process environment, not a committed file
or a shell command. **Never supply TradingView or broker passwords to this tool.**

Start without visual AI, verify numeric+image receipts, then enable visual AI at
the prompt if desired. Each call is capped at 650 output tokens, global interval
60 seconds and per-source interval 300 seconds. Gateway credits/auth must work.
Do not disable Deployment Protection; use existing authorized automation access.

## Server configuration

Apply `sql/011_chart_reader.sql` to the AEGIS database. Configure
`AEGIS_CHART_TOKEN` (32+ random characters) **only for agent-city-v1 preview**.
Configure `AEGIS_CHART_VISION_MODEL` using a verified vision-capable Gateway ID.
On Vercel, OIDC avoids a separate provider key. No trading credentials are needed.

GET `/api/stage3?chart=1` returns snapshots with their receipt time, instrument,
freshness, numeric observers and last visual report. GET `?chart=gold` refreshes
the rate-limited REST fallback. Signed POST `?chart=1` either ingests a Desktop
snapshot or requests `{ "action":"analyze", "source_id":"..." }`.

HMAC-SHA256 signs `timestamp + '.' + exact_request_bytes`; headers are
`X-Aegis-Timestamp` and `X-Aegis-Signature`. The receiver rejects stale signatures,
replay charts, duplicate/out-of-order candles, nonfinite prices, synthetic bars,
unsupported symbols and full-screen captures. Signed retries are idempotent.

The UI shows the image capture time independently of the newest numerical
snapshot. A visual report is commentary, not verified evidence of broker fills.
This release does not give an LLM order tools or modify the Bot branch/services.

## Verification

```sh
python -m pytest tests/test_chart_reader.py tests/test_chart_api.py tests/test_stream_worker.py
node --test tests/test_chart_companion.mjs
```

Unit fixtures do not prove a live TradingView session. The definitive Desktop
check is a fresh `TRADINGVIEW_DESKTOP` receipt with the exact visible symbol,
timeframe and cropped image, followed by an actual stored visual model report.
