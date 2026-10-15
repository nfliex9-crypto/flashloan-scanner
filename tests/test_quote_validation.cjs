const {test}=require("node:test");
const assert=require("node:assert/strict");
const {pathToFileURL}=require("node:url");
const {resolve}=require("node:path");
const load=()=>import(pathToFileURL(resolve("tools/quote_validation.mjs")).href);
test("real provider quote validated and tagged read-only",async()=>{
  const {normalizeQuote}=await load();
  const now=new Date("2026-01-05T12:00:02Z");
  const data={symbol:"F.US.MES",lastPrice:6000.25,bestBid:6000.0,bestAsk:6000.5,timestamp:"2026-01-05T12:00:00Z"};
  const quote=normalizeQuote("CON.F.US.MES.H26",data,now);
  assert.equal(quote.trading_enabled,false);
  assert.equal(quote.lag_ms,2000);
  assert.equal(quote.best_ask,6000.5);
});
test("stale and crossed bid/ask quotes are rejected",async()=>{
  const {normalizeQuote}=await load();
  const now=new Date("2026-01-05T12:05:00Z");
  const data={lastPrice:6000,bestBid:6000,bestAsk:6001,timestamp:"2026-01-05T12:00:00Z"};
  assert.throws(()=>normalizeQuote("CON.F.US.MES.H26",data,now),/Stale/);
  assert.throws(()=>normalizeQuote("CON.F.US.MES.H26",{...data,bestBid:6003},new Date("2026-01-05T12:00:00Z")),/Invalid bid/);
});
test("heartbeat does not falsely report live",async()=>{
  const {monitorStatus}=await load();
  assert.equal(monitorStatus(null,1000),"WAITING_FOR_PROVIDER");
  assert.equal(monitorStatus(1000,1100),"LIVE_DATA_RECEIVED");
  assert.equal(monitorStatus(1000,40000),"STALE_FEED");
});
