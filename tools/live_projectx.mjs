/**
 * LOCAL ProjectX market SignalR reader. NO orders and NO broker trading.
 * Run only with an authorized ProjectX subscription and from an approved device.
 *
 * PROJECTX_USERNAME=<platform username>
 * PROJECTX_API_KEY=<your secret; never commit>
 * PROJECTX_CONTRACT_ID=CON.F.US.MES.<active-expiry>
 * node tools/live_projectx.mjs
 */
import fs from "node:fs";
import path from "node:path";
import signalR from "@microsoft/signalr";
import {normalizeQuote,monitorStatus} from "./quote_validation.mjs";
const {HubConnectionBuilder,HttpTransportType,LogLevel}=signalR;
const user=process.env.PROJECTX_USERNAME;
const key=process.env.PROJECTX_API_KEY;
const contract=process.env.PROJECTX_CONTRACT_ID;
if(!user || !key || !/^CON\.[A-Z0-9.]+$/i.test(contract||"")){
  process.stderr.write("Missing PROJECTX_USERNAME, PROJECTX_API_KEY or valid PROJECTX_CONTRACT_ID. Check docs.\n");
  process.exit(2);
}
let token=null;
let connection=null;
let latest=null;
let lastReceived=null;
let accepting=true;
const output=path.resolve("data/projectx-latest-quote.json");
async function authenticate(){
  const ctl=new AbortController();
  const timer=setTimeout(()=>ctl.abort(),15000);
  try{
    const r=await fetch("https://api.topstepx.com/api/Auth/loginKey",{
      method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({userName:user,apiKey:key}),signal:ctl.signal});
    if(!r.ok)throw Error("HTTP "+r.status);
    const p=await r.json();
    if(p.success!==true || !p.token)throw Error("Provider rejected credentials/subscription");
    token=p.token;
  } finally {clearTimeout(timer)}
}
function persist(){
  if(!latest)return;
  fs.mkdirSync(path.dirname(output),{recursive:true});
  // Replace a snapshot rather than accumulating unbounded, proprietary tick logs.
  const temp=output+".tmp";
  fs.writeFileSync(temp,JSON.stringify({...latest,health:monitorStatus(lastReceived)},null,2)+"\n",{mode:0o600});
  fs.renameSync(temp,output);
}
async function subscribe(){
  if(!connection || !accepting)return;
  await connection.invoke("SubscribeContractQuotes",contract);
  process.stdout.write("Subscribed to authorized read-only quotes for "+contract+"\n");
}
async function boot(){
  await authenticate();
  connection=new HubConnectionBuilder()
    .withUrl("https://rtc.topstepx.com/hubs/market",{
      transport:HttpTransportType.WebSockets,
      skipNegotiation:true,
      accessTokenFactory:()=>token,
      timeout:10000
    })
    .configureLogging(LogLevel.Error)
    .withAutomaticReconnect([0,2000,10000,30000])
    .build();
  connection.on("GatewayQuote",(id,data)=>{
    if(!accepting || id!==contract)return;
    try{
      const q=normalizeQuote(id,data);
      latest=q;lastReceived=Date.now();
    }catch(e){process.stderr.write("Dropped invalid/stale quote: "+e.message+"\n")}
  });
  connection.onreconnected(()=>{subscribe().catch(()=>process.stderr.write("Resubscribe failed\n"))});
  connection.onclose(()=>{process.stderr.write("SignalR disconnected; no data is live\n")});
  await connection.start();
  await subscribe();
  setInterval(()=>{
    if(!accepting)return;
    const status=monitorStatus(lastReceived);
    persist();
    process.stdout.write(JSON.stringify({
      status,contract_id:contract,received_at:latest?.received_at_utc||null,
      last:status==="LIVE_DATA_RECEIVED"?latest?.last_price:null,
      bid:status==="LIVE_DATA_RECEIVED"?latest?.best_bid:null,
      ask:status==="LIVE_DATA_RECEIVED"?latest?.best_ask:null
    })+"\n");
  },1000);
  // Refresh the bearer token before its documented 24-hour expiry.
  setInterval(()=>{authenticate().catch(()=>process.stderr.write("Token refresh failed; restart local feed\n"))},
    22*60*60*1000);
  process.once("SIGINT",shutdown);process.once("SIGTERM",shutdown);
}
async function shutdown(){
  accepting=false;
  try{await connection?.stop()}finally{process.exit(0)}
}
boot().catch(()=>{
  process.stderr.write("Cannot establish authorized live data feed. Verify API subscription and local permissions.\n");
  process.exitCode=1;
});
