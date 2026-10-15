// Strictly read-only normalization. No order functionality in this module.
export function normalizeQuote(contractId, data, receivedAt = new Date()) {
  if(typeof contractId !== "string" || !/^CON\.[A-Z0-9.]+$/i.test(contractId)) {
    throw new Error("Invalid contract identifier");
  }
  if(!data || typeof data !== "object") throw new Error("Invalid quote payload");
  const last=Number(data.lastPrice),bid=Number(data.bestBid),ask=Number(data.bestAsk);
  if(![last,bid,ask].every(Number.isFinite) || last<=0 || bid<=0 || ask<=0 || bid>ask)
    throw new Error("Invalid bid/ask/last values");
  const rawStamp=data.timestamp||data.lastUpdated;
  if(typeof rawStamp!=="string" || !/(Z|[+-]\d\d:\d\d)$/i.test(rawStamp))
    throw new Error("Missing timezone-aware exchange timestamp");
  const stamp=new Date(rawStamp);
  if(Number.isNaN(stamp.getTime()))throw new Error("Invalid market timestamp");
  const ageMs=receivedAt.getTime()-stamp.getTime();
  if(ageMs < -30_000 || ageMs > 120_000) throw new Error("Stale or future quote");
  return Object.freeze({
    contract_id:contractId,
    symbol:String(data.symbol||""),
    best_bid:bid,best_ask:ask,last_price:last,
    exchange_timestamp:stamp.toISOString(),
    received_at_utc:receivedAt.toISOString(),
    lag_ms:ageMs,
    source:"ProjectX market SignalR (authorized local feed)",
    mode:"read_only",trading_enabled:false
  });
}

export function monitorStatus(lastReceived, now = Date.now(), maxAgeMs = 30_000) {
  if(lastReceived===null)return "WAITING_FOR_PROVIDER";
  return (now-lastReceived>maxAgeMs)?"STALE_FEED":"LIVE_DATA_RECEIVED";
}
