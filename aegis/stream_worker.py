"""Always-on *public market data* + independent shadow-only micro-paper engine.

Start in a separate process/container: python -m aegis.stream_worker
This never imports a broker order SDK, reads OANDA keys, or touches main Paper.
Gold realtime streaming is NOT implied: currently the public Kraken crypto feed
is supported. Twelve Data gold has separate quotas/entitlements to verify.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import deque
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

from .live_lab import Candle, fetch_ohlc
from .stream_core import ALLOWED_MINUTES, ClosedBarGate, CompletedBar, fresh_closed_history
from .stream_paper import persist_closed_stream_bar

KRAKEN_PUBLIC_WS = "wss://ws.kraken.com/v2"
PAIRS = {"BTC": ("BTC/USD", "XBTUSD"), "ETH": ("ETH/USD", "ETHUSD")}
MAX_ENTRY_OBSERVATION_LAG_S = 10
log = logging.getLogger("aegis.stream")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def enabled_symbols() -> list[str]:
    raw = os.getenv("AEGIS_STREAM_SYMBOLS", "BTC").strip()
    names = [x.strip().upper() for x in raw.split(",")]
    if not names or len(set(names)) != len(names) or any(n not in PAIRS for n in names):
        raise ValueError("AEGIS_STREAM_SYMBOLS must contain unique BTC and/or ETH")
    return names


def _connect():
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL must be configured for independent stream process")
    return psycopg.connect(url, row_factory=dict_row, connect_timeout=8)


def _write_status(name: str, state: str, *, closed_ts: int | None = None) -> None:
    # No credential strings, URLs, or raw exception output can enter telemetry.
    now=_now()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO aegis.stream_status(stream_name,state,last_message_at,"
                "last_closed_bar,last_error,updated_at) "
                "VALUES(%s,%s,%s,%s,NULL,%s) "
                "ON CONFLICT(stream_name) DO UPDATE SET "
                "state=EXCLUDED.state,last_message_at=EXCLUDED.last_message_at,"
                "last_closed_bar=COALESCE(EXCLUDED.last_closed_bar,"
                "aegis.stream_status.last_closed_bar),"
                "last_error=NULL,updated_at=EXCLUDED.updated_at",
                (name,state,now,
                 datetime.fromtimestamp(closed_ts,timezone.utc) if closed_ts else None,now))


class KrakenMicroWorker:
    def __init__(self, symbols: list[str]) -> None:
        if any(s not in PAIRS for s in symbols) or not symbols:
            raise ValueError("Only public Kraken BTC/ETH market symbols supported")
        self.symbols=symbols
        self.gate=ClosedBarGate()
        self.history: dict[tuple[str,int],deque[Candle]]={}
        self.stats={"closed_bars":0,"entries":0,"exits":0,"skipped_late":0,
                    "skipped_history":0,"duplicates":0}

    async def bootstrap_interval(self,minute:int)->None:
        """Resubscribe one timeframe without disturbing other WS sockets."""
        if minute not in ALLOWED_MINUTES:
            raise ValueError("Unsupported public OHLC interval")
        now=_now().timestamp()
        for sym in self.symbols:
            self.gate.current.pop((sym,minute),None)
            try:
                raw=await asyncio.to_thread(fetch_ohlc,PAIRS[sym][1],minute)
                past=[x for x in raw if x.ts+minute*60<=now]
                self.history[(sym,minute)]=deque(past[-720:],maxlen=720)
                # Freeze first historical result; reconnects cannot optimize
                # the holdout or overwrite a failed screen after seeing PnL.
                if sym=='BTC':
                    await asyncio.to_thread(self.record_screen,sym,minute,past[-720:])
            except Exception:
                self.history[(sym,minute)]=deque(maxlen=720)
                log.warning("Warmup unavailable: %s %dm. New entries disabled.",sym,minute)
        log.info("Loaded real closed-candle warmup for %dm public market feed",minute)

    @staticmethod
    def record_screen(symbol,minute,bars):
        from .historical_receipts import build_receipts,persist_receipts
        from .stream_paper import stream_agent_id,STRATEGIES,MICRO_DIRECTIONS
        ids=[stream_agent_id(symbol,minute,s,d) for s in STRATEGIES for d in MICRO_DIRECTIONS]
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT count(*) AS n FROM aegis.stream_historical_screens WHERE agent_id=ANY(%s)',(ids,))
                if cur.fetchone()['n']==len(ids):return
            persist_receipts(conn,build_receipts(symbol,minute,bars))

    async def _persist(self, event:CompletedBar, bars:list[Candle])->dict:
        def work():
            with _connect() as conn:
                return persist_closed_stream_bar(conn,event,bars)
        return await asyncio.to_thread(work)

    async def handle(self,message:dict,now:datetime|None=None)->list[dict]:
        now=now or _now()
        events=self.gate.consume(message,now)
        results=[]
        for event in events:
            key=(event.symbol,event.interval_minutes)
            if key not in self.history:
                continue
            history=self.history[key]
            if history and event.candle.ts < history[-1].ts:
                continue
            if history and event.candle.ts==history[-1].ts:
                history[-1]=event.candle
            elif history and event.candle.ts-history[-1].ts==event.interval_minutes*60:
                history.append(event.candle)
            else:
                # Warmup gap or missing history: no trading across the gap.
                history.clear()
                history.append(event.candle)
                self.stats["skipped_history"]+=1
                # Keep one verified closed candle for existing stop/target
                # protection; missing 95-bar history disables NEW entries.
            self.stats["closed_bars"]+=1
            age=now.timestamp()-event.next_start
            if not (0<=age<=MAX_ENTRY_OBSERVATION_LAG_S):
                # Simulating a retroactive next-open fill would introduce
                # false PnL; decline even if data can be used as history.
                self.stats["skipped_late"]+=1
                continue
            if not fresh_closed_history(list(history),event.interval_minutes):
                self.stats["skipped_history"]+=1
                # Do not skip the atomic ledger entirely: existing stops
                # can still be evaluated on the newly CLOSED valid bar.
                # fill_decision itself vetoes fresh entries without warmup.
            result=await self._persist(event,list(history))
            if not result["processed"]:
                self.stats["duplicates"]+=1
                continue
            self.stats["entries"]+=result["entries"]
            self.stats["exits"]+=result["exits"]
            results.append({"symbol":event.symbol,"interval":event.interval_minutes,
                            "bar_start":event.candle.ts,**result})
        return results

    async def stream_interval_once(self,interval:int)->None:
        """One interval per socket: Kraken rejects parallel intervals per symbol."""
        from websockets.asyncio.client import connect
        await self.bootstrap_interval(interval)
        name=f"kraken-public-micro-{interval}m"
        async with connect(KRAKEN_PUBLIC_WS,open_timeout=12,
                           ping_interval=20,ping_timeout=20,max_size=1_000_000) as ws:
            await ws.send(json.dumps({
                "method":"subscribe",
                "params":{"channel":"ohlc",
                          "symbol":[PAIRS[s][0] for s in self.symbols],
                          "interval":interval,"snapshot":True},
                "req_id":interval}))
            log.info("Subscribed to public Kraken %dm candle socket; awaiting ack",interval)
            await asyncio.to_thread(_write_status,name,"STARTING")
            verified=False
            last_heartbeat=0.0
            async for raw in ws:
                packet=json.loads(raw)
                if packet.get("method")=="subscribe":
                    if packet.get("success") is False:
                        explanation=str(packet.get("error","UNKNOWN"))
                        code="".join(ch for ch in explanation if ch.isalnum() or ch in "-_ :.")[:120]
                        log.warning("Kraken %dm subscription rejected: %s",interval,code)
                        raise RuntimeError("Kraken public data subscription rejected")
                    if packet.get("success") is True:
                        ack=packet.get("result") or {}
                        if ack.get("interval")!=interval:
                            raise RuntimeError("Kraken acknowledged unexpected candle interval")
                        if not verified:
                            verified=True
                            log.info("Kraken accepted public %dm candle stream",interval)
                            await asyncio.to_thread(_write_status,name,"CONNECTED")
                results=await self.handle(packet)
                for item in results:
                    if item["interval"]!=interval:
                        raise RuntimeError("Candle routed to wrong interval socket")
                    log.info("Verified %s %dm closed bar %s | %d virtual entries | %d exits",
                             item["symbol"],interval,item["bar_start"],
                             item["entries"],item["exits"])
                    await asyncio.to_thread(_write_status,name,"CONNECTED",
                                            closed_ts=item["bar_start"])
                # A heartbeat should represent actual received market messages,
                # not just a socket handshake, and should not spam Neon.
                if verified and packet.get("channel")=="ohlc":
                    stamp=_now().timestamp()
                    if stamp-last_heartbeat>=30:
                        await asyncio.to_thread(_write_status,name,"CONNECTED")
                        last_heartbeat=stamp

    async def interval_forever(self,interval:int)->None:
        delay=2
        name=f"kraken-public-micro-{interval}m"
        while True:
            try:
                await self.stream_interval_once(interval)
                delay=2
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("Kraken %dm feed degraded (%s); independent reconnect pending.",
                            interval,type(exc).__name__)
                try:
                    await asyncio.to_thread(_write_status,name,"DEGRADED")
                except Exception:
                    log.warning("Neon heartbeat unavailable for %dm; no synthetic fills.",interval)
                await asyncio.sleep(delay)
                delay=min(45,delay*2)

    async def forever(self)->None:
        await asyncio.gather(*(self.interval_forever(n) for n in ALLOWED_MINUTES))


async def main()->None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    symbols=enabled_symbols()
    # Explicit isolation: no worker code uses an OANDA, Alpaca or exchange
    # private trading credential; only public websocket plus Neon ledger.
    if not os.getenv("DATABASE_URL"):
        raise RuntimeError("Worker needs DATABASE_URL to persist its results")
    await KrakenMicroWorker(symbols).forever()


if __name__=="__main__":
    asyncio.run(main())
