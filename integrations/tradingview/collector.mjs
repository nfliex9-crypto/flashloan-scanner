/** Read-only companion for tradesdontlie/tradingview-mcp, reviewed at c05b8f5.
 * No MCP server, launch, navigation, Pine execution or broker tool is exposed.
 */
import { createHmac } from 'node:crypto';
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';
import { execFileSync } from 'node:child_process';

export const UPSTREAM_COMMIT = 'c05b8f5755ed8e64ea242de88ddbf46aa24d56a4';
const INTERVALS = new Set(['5','15','60','240']);
const SYMBOL = /^(KRAKEN:(BTC|ETH)USD|[A-Z0-9_]{2,24}:XAUUSD|COMEX:(MGC|GC)([FGHJKMNQUVXZ][0-9]{4}|1!))$/;

export function makePayload(before, after, ohlcv, studies, replay, image, now = new Date()) {
  if (!before.success || !after.success || !ohlcv.success || replay !== false)
    throw new Error('Chart/replay state is unverified. Disable Bar Replay.');
  if (before.symbol !== after.symbol || before.resolution !== after.resolution || before.chartType !== after.chartType)
    throw new Error('Chart changed during capture; sample discarded.');
  if (!SYMBOL.test(before.symbol) || !INTERVALS.has(before.resolution))
    throw new Error('Open XAUUSD, COMEX GC/MGC, or Kraken BTCUSD/ETHUSD on 5m, 15m, 1h or 4h.');
  if (![0,1,9].includes(before.chartType)) throw new Error('Use standard candles or bars, not synthetic chart types.');
  if (!Array.isArray(ohlcv.bars) || ohlcv.bars.length < 55) throw new Error('Wait for at least 55 chart candles.');
  const cleanStudies = (studies.studies || []).slice(0,20).map(s => ({
    name: String(s.name || '').slice(0,60),
    values: Object.fromEntries(Object.entries(s.values || {}).slice(0,12).flatMap(([k,v]) => {
      // Reject formatted suffixes, NaN and free text rather than guessing units.
      const text=String(v).replaceAll(',','').trim();
      return /^-?\d+(\.\d+)?$/.test(text) && Number.isFinite(Number(text)) ? [[k.slice(0,40),Number(text)]] : [];
    }))
  }));
  return {version:1, source:'TRADINGVIEW_DESKTOP', symbol:before.symbol,
    interval_minutes:Number(before.resolution), chart_type:before.chartType,
    replay:false, chart_only:true, observed_at:now.toISOString(),
    bars:ohlcv.bars.slice(-240).map(b => ({time:b.time,open:b.open,high:b.high,low:b.low,close:b.close,volume:b.volume ?? null})),
    studies:cleanStudies, ...(image ? {image_png:image} : {})};
}

export function signedHeaders(raw, token, timestamp=Math.floor(Date.now()/1000).toString()) {
  return {'Content-Type':'application/json','X-Aegis-Timestamp':timestamp,
    'X-Aegis-Signature':createHmac('sha256',token).update(timestamp+'.'+raw).digest('hex')};
}

async function main() {
  const root=process.env.TRADINGVIEW_MCP_DIR;
  const token=process.env.AEGIS_CHART_TOKEN;
  if (!root || !token || token.length<32) throw new Error('Set TRADINGVIEW_MCP_DIR and AEGIS_CHART_TOKEN (never send passwords).');
  const upstream=execFileSync('git',['-C',root,'rev-parse','HEAD'],{encoding:'utf8'}).trim();
  if (upstream!==UPSTREAM_COMMIT) throw new Error('Upstream revision differs from the reviewed version. See README.');
  const destination=new URL(process.env.AEGIS_URL || 'https://flashloan-scanner-git-agent-city-v1-flashloan.vercel.app');
  if (destination.protocol!=='https:' || destination.username || destination.password) throw new Error('AEGIS_URL must be HTTPS without embedded credentials.');
  destination.pathname='/api/stage3'; destination.search='?chart=1'; destination.hash='';
  // The debugging socket must remain local to this laptop.
  process.env.TV_CDP_HOST='127.0.0.1'; process.env.CDP_HOST='127.0.0.1';
  process.env.TV_CDP_PORT='9222'; process.env.CDP_PORT='9222';
  const moduleAt=name=>import(pathToFileURL(resolve(root,'src',name)).href);
  const chart=await moduleAt('core/chart.js');
  const data=await moduleAt('core/data.js');
  const connection=await moduleAt('connection.js');
  let lastImage=0,lastAnalysis=0,stopped=false;
  process.on('SIGINT',()=>{stopped=true});
  async function post(payload) {
    const raw=JSON.stringify(payload), headers=signedHeaders(raw,token);
    if (process.env.VERCEL_AUTOMATION_BYPASS_SECRET)
      headers['x-vercel-protection-bypass']=process.env.VERCEL_AUTOMATION_BYPASS_SECRET;
    const response=await fetch(destination,{method:'POST',headers,body:raw,redirect:'error',signal:AbortSignal.timeout(55000)});
    if (!response.ok) {
      let code='request_rejected';
      try {code=(await response.json()).error || code}catch{}
      throw new Error(`AEGIS HTTP ${response.status}: ${String(code).slice(0,70)}. Check private deployment access/configuration.`);
    }
    return response.json();
  }
  console.log('AEGIS chart companion: local read-only capture. Ctrl+C stops. No order tools.');
  while(!stopped) {
    try {
      const before=await chart.getState();
      const replayPath=await connection.getReplayApi();
      const replay=await connection.evaluate(`(function(){var v=${replayPath}.isReplayStarted();return typeof v==='boolean'?v:(v&&typeof v.value==='function'?v.value():null)})()`);
      const ohlcv=await data.getOhlcv({count:240});
      const studies=await data.getStudyValues();
      let image;
      if (Date.now()-lastImage>=60000) {
        // Unlike upstream captureScreenshot(), never fall back to full screen.
        const clip=await connection.evaluate(`(function(){var e=document.querySelector('[data-name="pane-canvas"]');if(!e)return null;var r=e.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,scale:1}})()`);
        if (!clip || clip.width<200 || clip.height<100 || clip.width>4000 || clip.height>2500)
          throw new Error('Chart-only crop not available; full-screen capture refused.');
        const cdp=await connection.getClient();
        image=(await cdp.Page.captureScreenshot({format:'png',clip})).data;
        if (image.length>930000) throw new Error('Chart image too large; reduce TradingView window size.');
      }
      const after=await chart.getState();
      const payload=makePayload(before,after,ohlcv,studies,replay,image);
      const ack=await post(payload);
      if(image)lastImage=Date.now();
      console.log(`${payload.observed_at} ${payload.symbol} ${payload.interval_minutes}m ${ack.freshness?.state} ${ack.written?'saved':'duplicate'}`);
      // Paid image analysis is explicit and bounded. Numerical capture is always independent.
      if(image && process.env.AEGIS_VISION==='1' && Date.now()-lastAnalysis>=300000) {
        lastAnalysis=Date.now();
        await post({action:'analyze',source_id:ack.source_id});
        console.log('Visual report saved.');
      }
    } catch(error) {console.error(String(error.message).slice(0,200));}
    if(!stopped) await new Promise(resolve=>setTimeout(resolve,5000));
  }
  process.exit(0);
}

if (process.argv[1] && import.meta.url===pathToFileURL(resolve(process.argv[1])).href)
  main().catch(error=>{console.error(error.message);process.exitCode=1});
