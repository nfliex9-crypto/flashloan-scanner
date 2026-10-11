import test from 'node:test';
import assert from 'node:assert/strict';
import { makePayload, signedHeaders } from '../integrations/tradingview/collector.mjs';

const state={success:true,symbol:'KRAKEN:BTCUSD',resolution:'5',chartType:1};
const candles={success:true,bars:Array.from({length:60},(_,i)=>({time:1700000000+i*300,open:1,high:2,low:1,close:2,volume:0}))};
test('changed chart identity or synthetic/replay candles cannot be uploaded',()=>{
  assert.throws(()=>makePayload(state,{...state,symbol:'COMEX:MGCZ2026'},candles,{},false));
  assert.throws(()=>makePayload(state,state,candles,{},true));
  assert.throws(()=>makePayload({...state,chartType:8},{...state,chartType:8},candles,{},false));
});
test('only numerical study values survive; no account data or scripts copied',()=>{
  const d=makePayload(state,state,candles,{studies:[{name:'RSI',values:{rsi:'55.2',secret:'password',units:'12M'},inputs:{script:'private'}}]},false);
  assert.deepEqual(d.studies,[{name:'RSI',values:{rsi:55.2}}]);
  assert.equal(d.chart_only,true);
});
test('request signature changes when payload changes',()=>{
  const a=signedHeaders('{}','x'.repeat(40),'1700000000');
  const b=signedHeaders('{ }','x'.repeat(40),'1700000000');
  assert.notEqual(a['X-Aegis-Signature'],b['X-Aegis-Signature']);
  assert.equal(a['X-Aegis-Signature'].length,64);
});
