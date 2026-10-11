"""Independent market reader. No paper engine, broker, order or trading SDK."""
from __future__ import annotations
import asyncio
import json
import logging
from datetime import datetime,timezone

from .chart_reader import INTERVALS,normalize
from .chart_store import persist
from .live_lab import fetch_ohlc
from .stream_core import parse_kraken_bar

log=logging.getLogger('aegis.chart_reader')


async def observe(interval, queue):
    from websockets.asyncio.client import connect
    delay=2
    while True:
        try:
            history={b.ts:b for b in await asyncio.to_thread(fetch_ohlc,'XBTUSD',interval)}
            last_saved=0
            async with connect('wss://ws.kraken.com/v2',open_timeout=12,ping_interval=20,ping_timeout=20,max_size=1000000) as ws:
                await ws.send(json.dumps({'method':'subscribe','params':{'channel':'ohlc','symbol':['BTC/USD'],'interval':interval,'snapshot':True},'req_id':interval}))
                verified=False
                async for raw in ws:
                    packet=json.loads(raw)
                    if packet.get('method')=='subscribe':
                        if packet.get('success') is not True or packet.get('result',{}).get('interval')!=interval:
                            raise ValueError('kraken_subscription_rejected')
                        verified=True;delay=2
                        log.info('Kraken chart feed %sm subscribed',interval)
                    if not verified or packet.get('channel')!='ohlc' or packet.get('type') not in ('snapshot','update'):
                        continue
                    now=datetime.now(timezone.utc)
                    for row in packet.get('data',[]):
                        symbol,minute,bar=parse_kraken_bar(row)
                        if symbol!='BTC' or minute!=interval or bar.ts>now.timestamp()+5:
                            raise ValueError('unexpected_chart_bar')
                        history[bar.ts]=bar
                    history=dict(sorted(history.items())[-240:])
                    if now.timestamp()-last_saved<5 or len(history)<55:
                        continue
                    doc={'version':1,'source':'KRAKEN_WS','symbol':'KRAKEN:BTCUSD','interval_minutes':interval,
                         'observed_at':now.isoformat(),'bars':[{'time':b.ts,'open':b.open,'high':b.high,
                          'low':b.low,'close':b.close,'volume':b.volume} for b in history.values()]}
                    try:
                        queue.put_nowait(doc);last_saved=now.timestamp()
                    except asyncio.QueueFull:
                        pass  # Do not let a database outage freeze or grow the stream.
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning('Chart feed %sm reconnecting (%s)',interval,type(exc).__name__)
            await asyncio.sleep(delay);delay=min(45,delay*2)


async def writer(queue):
    saved=0
    while True:
        raw=await queue.get()
        try:
            doc=normalize(raw)
            await asyncio.to_thread(persist,doc)
            saved+=1
            if saved%24==1:
                log.info('Chart observation stored: %s %sm at %s',doc['symbol'],doc['interval_minutes'],doc['observed_at'])
        except Exception as exc:
            log.warning('Chart storage unavailable (%s)',type(exc).__name__)
        finally:
            queue.task_done()


async def main():
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    queue=asyncio.Queue(maxsize=8)
    await asyncio.gather(writer(queue),*(observe(n,queue) for n in INTERVALS))


if __name__=='__main__':asyncio.run(main())
