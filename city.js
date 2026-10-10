/* AEGIS Agent City 3.0: every financial datum is sourced from Neon. */
const $ = (id) => document.getElementById(id);
const currency = (n) => new Intl.NumberFormat("en-US",{style:"currency",currency:"USD",maximumFractionDigits:2}).format(Number(n)||0);
const fixed = (v,d=2) => Number(v||0).toFixed(d);
const percent = (v,d=2) => fixed(100*Number(v||0),d)+"%";
const sign = (v) => Number(v||0)>=0?"positive":"negative";
const safe = (v) => String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const utc = (v) => v ? new Date(v).toLocaleString("en-GB",{month:"short",day:"2-digit",hour:"2-digit",minute:"2-digit",timeZone:"UTC"})+" UTC" : "—";
const dateTime = (v) => v ? new Date(v).toLocaleString("en-GB",{timeZone:"UTC"})+" UTC" : "—";
let cityState=null,marketState=null,intelState=null,lastLedgerFeed=[],lastRankings=[];
let experimentDirty=false,experimentSaving=false;
let lastEventKeys=null, currentView="city", currentSelection=null, livePolling=false;
const towers=[
  {x:245,y:385},{x:405,y:338},{x:236,y:489},{x:396,y:484},
  {x:804,y:338},{x:956,y:391},{x:824,y:487},{x:990,y:499},
];
let selectedTowerMap=new Map();
let mobileCameraX=300;
let lastSceneDragAt=0;
function clampCamera(v){return Math.max(0,Math.min(600,v))}
function syncCamera(){
  const small=window.matchMedia("(max-width:620px)").matches;
  $("citySvg").setAttribute("viewBox",small?`${mobileCameraX} 0 600 620`:"0 0 1200 620");
}

function statusClass(role){
  if(role==="ACTIVE_PAPER"||role==="RESEARCH_ACTIVE")return "active";
  if(role==="HALTED")return "halted";
  if(role==="RESEARCH_HOLD")return "shadow";
  if(role==="CHALLENGER")return "challenger";
  return "shadow";
}
function effectiveRole(worker){
  const role=worker.role || (worker.status==="ACTIVE"?"RESEARCH_ACTIVE":"SHADOW");
  if(role==="ACTIVE_PAPER" && worker.status!=="ACTIVE")return "RESEARCH_HOLD";
  return role;
}
function symbolWorker(worker){
  return safe(worker.asset)+" / "+safe(worker.strategy);
}
function isReady(data){return data?.ok&&data?.initialized;}
function nowClock(){
  $("utcClock").textContent=new Date().toLocaleTimeString("en-GB",{hour12:false,timeZone:"UTC"})+" UTC";
  const n=new Date(),utcMin=n.getUTCMinutes(),utcSec=n.getUTCSeconds();
  // Monitoring runs at UTC :05, :20, :35, :50, while strategy
  // signals remain based on independently verified CLOSED hourly bars.
  const seconds=utcMin*60+utcSec;
  const next=[5,20,35,50,65].find(m=>m*60>seconds);
  const remaining=next*60-seconds;
  const mm=Math.floor(Math.max(0,remaining)/60),ss=Math.max(0,remaining)%60;
  $("nextScan").textContent=String(mm).padStart(2,"0")+":"+String(ss).padStart(2,"0");
}
function makeScene(workers){
  const byAsset={BTC:[],XAU:[]};
  workers.forEach(w=>{if(byAsset[w.asset])byAsset[w.asset].push(w)});
  byAsset.BTC.sort((a,b)=>a.strategy.localeCompare(b.strategy));
  byAsset.XAU.sort((a,b)=>a.strategy.localeCompare(b.strategy));
  const arranged=[...byAsset.BTC,...byAsset.XAU];
  const allWorkers=[...arranged,...workers.filter(w=>w.asset!=="BTC"&&w.asset!=="XAU")];
  let towersMarkup="",roads="";
  selectedTowerMap=new Map();
  arranged.slice(0,8).forEach((w,i)=>{
    const {x,y}=towers[i];
    selectedTowerMap.set(w.agent_id,{x,y,worker:w});
    const role=effectiveRole(w),cls=statusClass(role);
    const h=76+Math.min(57,Math.max(0,Number(w.survival_score||0)*.48))+(i%2)*14;
    const w1=27;
    roads+=`<path class="road-line" d="M ${x} ${y+7} Q ${(x+600)/2} ${y+90} 600 462"/>`;
    const win=[0,1,2,3,4].map(n=>`<circle class="window-dot" cx="-9" cy="${-h+22+n*15}" r="2"/><circle class="window-dot" cx="9" cy="${-h+26+n*15}" r="2"/>`).join("");
    const label=w.strategy==="Mean Reversion"?"MEAN REV":w.strategy.toUpperCase();
    towersMarkup+=`
    <g class="tower ${cls}" data-agent="${safe(w.agent_id)}" role="button" tabindex="0" aria-label="Open ${safe(w.asset)} ${safe(w.strategy)} details" transform="translate(${x} ${y})">
      <ellipse cx="0" cy="15" rx="51" ry="20" fill="#9385fe" opacity=".13"/>
      <ellipse class="tower-halo" cx="0" cy="7" rx="45" ry="18"/>
      <polygon class="tower-main" points="-27,${-h-5} 0,${-h+10} 0,0 -27,-15"/>
      <polygon class="tower-side" points="0,${-h+10} 27,${-h-5} 27,-15 0,0"/>
      <polygon class="tower-top" points="-27,${-h-5} 0,${-h-22} 27,${-h-5} 0,${-h+10}"/>
      <path d="M-27,-15 L0,0 L27,-15" fill="none" stroke="#bb9aff" stroke-opacity=".7"/>
      ${win}
      <circle class="tower-led" cx="0" cy="${-h-13}" r="5"/>
      <text x="0" y="${-h-42}" text-anchor="middle" class="tower-label">${safe(w.asset)}</text>
      <text x="0" y="${-h-28}" text-anchor="middle" class="tower-sub">${safe(label)}</text>
      <title>${safe(w.asset)} ${safe(w.strategy)} · ${safe(role)} · Forward net ${safe(currency(w.earned))}</title>
    </g>`;
  });
  $("sceneRoads").innerHTML=roads;
  $("sceneWorkers").innerHTML=towersMarkup;
  document.querySelectorAll("#sceneWorkers .tower").forEach(el=>{
    const handler=()=>showAgent(el.getAttribute("data-agent"));
    el.addEventListener("click",handler);
    el.addEventListener("keydown",ev=>{if(ev.key==="Enter"||ev.key===" "){ev.preventDefault();handler()}});
  });
  const active=allWorkers.filter(w=>w.status==="ACTIVE" && (effectiveRole(w)==="ACTIVE_PAPER"||effectiveRole(w)==="RESEARCH_ACTIVE")).length;
  $("activeWorkers").textContent=String(active)+" / "+allWorkers.length;
  $("onShiftDetails").textContent="BTC + XAU virtual Paper research · ETH available below";
  $("quickWorkers").innerHTML=allWorkers.map(w=>`<button class="worker-chip ${statusClass(effectiveRole(w))}" data-quickagent="${safe(w.agent_id)}">
    <strong>${symbolWorker(w)}</strong><small>${safe(effectiveRole(w))} · ${currency(w.earned)}</small></button>`).join("");
  document.querySelectorAll("[data-quickagent]").forEach(el=>el.addEventListener("click",()=>showAgent(el.dataset.quickagent)));
  syncCamera();
}

function paintIndividualTradeFeed(feed,workers){
  lastLedgerFeed=Array.isArray(feed)?feed:[];
  const select=$("agentTradeFilter");
  const selected=select.value;
  select.innerHTML='<option value="all">All agents</option>'+workers
    .map(w=>'<option value="'+safe(w.agent_id)+'">'+symbolWorker(w)+'</option>').join("");
  if([...select.options].some(o=>o.value===selected))select.value=selected;
  applyTradeFilters();
}
function applyTradeFilters(){
  const agent=$("agentTradeFilter").value;
  const book=$("tradeMarketFilter").value;
  const action=$("tradeActionFilter").value;
  const subset=lastLedgerFeed.filter(t=>(agent==="all"||t.agent_id===agent)
    &&(book==="all"||t.market===book)&&(action==="all"||t.action===action));
  $("agentTapeStats").textContent=subset.length+" ledger events · "+lastLedgerFeed.length+" returned";
  $("agentTradeFeed").innerHTML=subset.length?subset.slice(0,65).map(t=>{
    const isClose=t.action==="CLOSE", openStatus=t.state==="OPEN";
    const net=isClose&&t.realized_net_pnl!=null?currency(t.realized_net_pnl):
      openStatus&&t.unrealized_pnl!=null?"UNREALIZED "+currency(t.unrealized_pnl):"—";
    const cls=isClose?sign(t.realized_net_pnl):"";
    const fees=isClose?" · Fees "+currency(t.fee_total)+" · Slip "+currency(t.slippage_cost):"";
    const label=isClose?"CLOSED":"OPENED";
    return '<button class="agent-trade-item" data-ledgeragent="'+safe(t.agent_id)+'">'+
      '<span class="trade-state '+(isClose?"closed":"opened")+'">'+label+'</span>'+
      '<span class="trade-ledger-main"><strong>'+safe(t.agent_id)+'</strong>'+
      '<small>'+safe(t.symbol)+' · '+safe(t.market)+' · '+utc(t.timestamp)+'</small>'+
      '<small>Qty '+fixed(t.qty,6)+' · Entry '+currency(t.entry_price)+
      (isClose?' · Exit '+currency(t.exit_price):"")+
      (isClose?' · '+safe(t.reason||"CLOSED"):"")+fees+'</small></span>'+
      '<strong class="trade-ledger-pnl '+cls+'">'+net+'</strong></button>';
  }).join("")
  :'<div class="await">No persisted OPEN/CLOSE events match these filters. No trades are invented.</div>';
  document.querySelectorAll("[data-ledgeragent]").forEach(el=>
    el.addEventListener("click",()=>showAgent(el.dataset.ledgeragent)));
}
function paintStrategyFilterBoard(rankings){
  lastRankings=Array.isArray(rankings)?rankings:[];
  $("strategyFilterBoard").innerHTML=lastRankings.length?lastRankings.map((r,i)=>{
    const cls=r.state==="QUARANTINED"?"quarantine":r.state==="LEADING"?"leader":"observing";
    return '<button class="strategy-rank-row" data-rankagent="'+safe(r.agent_id)+'">'+
      '<strong class="strategy-rank-number">#'+(i+1)+'</strong>'+
      '<span class="strategy-rank-name"><strong>'+safe(r.asset)+' / '+safe(r.strategy)+'</strong>'+
      '<small>'+safe(r.reason)+'</small></span>'+
      '<span class="strategy-rank-metrics"><span>Costed '+Number(r.trades||0)+
      '</span><span>PF '+fixed(r.profit_factor,2)+'</span>'+
      '<span class="'+sign(r.net_pnl)+'">'+currency(r.net_pnl)+'</span></span>'+
      '<span class="strategy-rank-state '+cls+'">'+safe(r.state)+'</span></button>';
  }).join(""):'<div class="await">No rankings yet. Waiting for persisted forward costed fills.</div>';
  document.querySelectorAll("[data-rankagent]").forEach(el=>
    el.addEventListener("click",()=>showAgent(el.dataset.rankagent)));
}

function renderHorizonRouter(data){
  const router=data||{};
  const status=router.state||"INSUFFICIENT_FORWARD_EVIDENCE";
  $("horizonRouterState").textContent=status.replaceAll("_"," ");
  const winner=router.selected;
  const options=router.candidates||[];
  $("horizonRouterSummary").textContent=winner
    ?"Best forward-tested candidate: "+winner.asset+" / "+winner.interval+
      " / "+winner.horizon+" / "+(winner.strategy||"unknown strategy")+
      " / "+winner.direction+" · Not a demo/live order authorization"
    :"No qualifying timeframe yet · "+options.length+
      " candidates · Requires matching pre-forward OOS evidence and enough costed forward trades";
  $("horizonRouterBoard").innerHTML=options.length?options.map(o=>
    '<div class="strategy-rank-row">'+
      '<strong class="strategy-rank-number">'+safe(o.interval)+'</strong>'+
      '<span class="strategy-rank-name"><strong>'+safe(o.asset)+' / '+safe(o.direction)+' / '+safe(o.horizon)+'</strong>'+
      '<small>'+safe(o.strategy||"Unidentified strategy")+' · '+Number(o.trades)+' closed costed trades · '+fixed(o.observed_days,1)+
      ' observation days'+(o.selection_qualified?" · OOS + Forward qualified":o.qualified?" · Forward only; matching OOS pending":" · Pending: "+safe((o.failed_checks||[]).join(", ")))+'</small></span>'+
      '<span class="strategy-rank-metrics">PF '+fixed(o.profit_factor,2)+
      ' · <span class="'+sign(o.net_pnl)+'">'+currency(o.net_pnl)+'</span></span>'+
      '<span class="strategy-rank-state '+(o.selection_qualified?"leader":"observing")+'">'+
      (o.selection_qualified?"RESEARCH READY":"COLLECTING")+'</span></div>'
  ).join(""):'<div class="await">No settled costed forward micro trades to rank. Research selection waits for observed performance.</div>';
}

function renderDemoBrokerLedger(data,micro){
  const d=data||{};
  const m=micro||{};
  const accounts=(d.connected_accounts||[]).filter(a=>a.provider==="MT5_DEMO");
  const fills=(d.recent_fills||[]).filter(t=>t.provider==="MT5_DEMO");
  const provider=(name)=>accounts.find(x=>x.provider===name);
  const tile=(label,name)=>{
    const a=provider(name);
    const state=a?a.sync_status:"NOT LINKED";
    return '<div class="bt-metric"><small>'+label+'</small>'+
      '<strong>'+safe(state.replaceAll("_"," "))+'</strong>'+
      '<span class="bt-small-note">'+(a?"Last broker sync "+utc(a.last_synced)+" · "+safe(a.market):
      "Waiting for demo-only account connection")+'</span></div>';
  };
  const btcAgents=(m.agents||[]).filter(a=>a.symbol==="BTC");
  const intervals=m.active_intervals_minutes||[];
  const btcPaper=btcAgents.length && intervals.length
    ?"KRAKEN PAPER · "+intervals.length+" FRESH FEEDS"
    :btcAgents.length?"PAPER · WAITING FOR FRESH FEEDS":"PAPER · NOT INITIALIZED";
  $("demoBrokerSummary").innerHTML=tile("MT5 GOLD DEMO","MT5_DEMO")+
    '<div class="bt-metric"><small>BTC · KRAKEN PAPER</small><strong>'+safe(btcPaper)+
    '</strong><span class="bt-small-note">'+btcAgents.length+
    ' persisted BTC research agents · No exchange demo or real orders</span></div>';
  $("demoBrokerStatus").textContent=accounts.length
    ? accounts.length+" broker demo sources · "+fills.length+
      " recent confirmed execution rows · Order automation: OFF"
    : "Gold MT5 Demo not linked yet. Bitcoin remains in independent Kraken Paper research; no broker orders.";
  $("demoBrokerFeed").innerHTML=fills.length?fills.map(t=>
    '<div class="agent-trade-item bt-trade-item">'+
    '<span class="trade-state closed">'+safe(t.side)+'</span>'+
    '<span class="trade-ledger-main"><strong>'+safe(t.provider)+
    ' · '+safe(t.symbol)+'</strong>'+
    '<small>'+utc(t.executed_at)+' · Broker deal '+safe(t.external_id)+
    ' · Order '+safe(t.order_id||"—")+'</small>'+
    '<small>Price '+currency(t.price)+' · Qty '+fixed(t.qty,6)+
    ' · Fee '+fixed(t.fee,6)+' '+safe(t.fee_asset||"")+
    (t.net_pnl==null?" · Trade P&L not calculated for spot fills":
      " · Broker P&L "+currency(t.net_pnl))+'</small></span></div>'
  ).join(""):'<div class="await">No demo broker trade execution has been synchronized yet. We do not manufacture execution history.</div>';
}

function renderMicroEngine(data){
  const d=data||{};
  const mode=d.mode||"WORKER_NOT_DEPLOYED";
  $("microConnectionBadge").textContent=mode.replaceAll("_"," ");
  const statuses=d.sources||[];
  const newest=statuses[0];
  $("microMarketStatus").textContent=
    "Feed: "+safe(d.source||"Public Kraken BTC/ETH only")+" · "+
    (newest?"Last worker heartbeat "+utc(newest.updated_at):"No worker heartbeat recorded")+
    " · Live broker orders OFF";
  const agents=d.agents||[],open=d.open_positions||[],closed=d.recent_closed_trades||[],bars=d.bar_stats||[];
  const tile=(label,value)=>'<div class="bt-metric"><small>'+label+'</small><strong>'+value+'</strong></div>';
  $("microWorkerTiles").innerHTML=
    tile("MICRO AGENTS",agents.length)+tile("OPEN MICRO VIRTUAL",open.length)+
    tile("RECENT CLOSED FILLS",closed.length)+
    tile("ACTIVE DATA SERIES",bars.length)+tile("EXECUTION","PAPER ONLY");
  $("microTradeTape").innerHTML=closed.length?closed.slice(0,35).map(t=>
    '<div class="agent-trade-item bt-trade-item">'+
    '<span class="trade-state closed">'+safe(t.direction||"LONG")+'</span>'+
    '<span class="trade-ledger-main"><strong>'+safe(t.agent_id)+'</strong>'+
    '<small>'+safe(t.symbol)+' · '+safe(t.direction||"LONG")+' · '+Number(t.interval_minutes)+'m · '+
    utc(t.opened_at)+' → '+utc(t.closed_at)+'</small>'+
    '<small>Entry '+currency(t.entry_price)+' · Exit '+currency(t.exit_price)+
    ' · Qty '+fixed(t.qty,6)+' · Fees '+currency(Number(t.entry_fee)+Number(t.exit_fee))+
    ' · Slip '+currency(t.slippage_cost)+
    ' · Finance '+currency(t.financing_cost||0)+'</small></span>'+
    '<strong class="trade-ledger-pnl '+sign(t.net_pnl)+'">'+currency(t.net_pnl)+'</strong></div>'
  ).join(""):'<div class="await">No verified micro paper closes recorded. '+(d.is_connected?"Waiting for actual signals and trades.":"Worker is not yet running or is stale.")+'</div>';
}
const EXPERIMENT_NAMES=["EMA Cross","RSI Pullback","Channel Breakout"];
function renderResearchLab(d){
  const c=d.experiment_controls;
  if(!c)return;
  if(!experimentDirty){
    $("expEnabled").checked=Boolean(c.enabled);
    $("expAssetBTC").checked=c.assets.includes("BTC");
    $("expAssetXAU").checked=c.assets.includes("XAU");
    $("expEMA").checked=c.strategies.includes("EMA Cross");
    $("expRSI").checked=c.strategies.includes("RSI Pullback");
    $("expChannel").checked=c.strategies.includes("Channel Breakout");
    $("expLimit").value=String(c.max_candidates);
  }
  $("labEngineStatus").textContent=c.enabled?"EXPERIMENTS ENABLED · VIRTUAL PAPER ONLY":"EXPERIMENTS PAUSED · NO NEW CANDIDATES";
  $("labEngineUpdated").textContent="Last saved "+utc(c.updated_at)+(experimentDirty?" · UNSAVED CHANGES":"");
  const workers=(d.workers||[]).filter(w=>EXPERIMENT_NAMES.includes(w.strategy));
  const counts={quarantined:workers.filter(w=>w.strategy_filter?.state==="QUARANTINED").length,
    collecting:workers.filter(w=>w.strategy_filter?.state==="COLLECTING").length};
  const count=d.last_run?.summary?.experiment_candidates_evaluated;
  $("labCandidateSummary").textContent=
    workers.length+" persistent candidates · "+counts.collecting+" collecting · "+counts.quarantined+
    " quarantined · "+(count==null?"Next verified hourly trial pending":count+" evaluated last hourly cycle");
  $("labCandidateBoard").innerHTML=workers.length?workers.map(w=>{
    const filter=w.strategy_filter||{},st=filter.state||"COLLECTING";
    const cls=st==="QUARANTINED"?"quarantine":st==="LEADING"?"leader":"observing";
    return '<button class="strategy-rank-row" data-experimentagent="'+safe(w.agent_id)+'">'+
      '<strong class="strategy-rank-number">◈</strong>'+
      '<span class="strategy-rank-name"><strong>'+symbolWorker(w)+'</strong>'+
      '<small>'+safe(filter.reason||"Waiting for costed Paper research")+'</small></span>'+
      '<span class="strategy-rank-metrics"><span>'+Number(filter.trades||0)+' costed</span>'+
      '<span>PF '+fixed(filter.profit_factor||0,2)+'</span>'+
      '<span class="'+sign(filter.net_pnl)+'">'+currency(filter.net_pnl)+'</span></span>'+
      '<span class="strategy-rank-state '+cls+'">'+safe(st)+'</span></button>';
  }).join(""):'<div class="await">No experimental agents registered yet. The first research run after activation creates them.</div>';
  $("labCandidateBoard").querySelectorAll("[data-experimentagent]").forEach(el=>
    el.addEventListener("click",()=>showAgent(el.dataset.experimentagent)));
}
function selectedExperimentSettings(){
  const assets=[];
  if($("expAssetBTC").checked)assets.push("BTC");
  if($("expAssetXAU").checked)assets.push("XAU");
  const strategies=[];
  if($("expEMA").checked)strategies.push("EMA Cross");
  if($("expRSI").checked)strategies.push("RSI Pullback");
  if($("expChannel").checked)strategies.push("Channel Breakout");
  if(!assets.length||!strategies.length)throw new Error("Choose at least one market and one strategy.");
  return {enabled:$("expEnabled").checked,assets,strategies,
    max_candidates:Number($("expLimit").value)};
}
async function checkResearchWriteReadiness(){
  const button=$("expSave"),key=$("expOwnerToken");
  button.disabled=true;
  key.disabled=true;
  try{
    const res=await fetch("/api/stage3?capabilities=1",{cache:"no-store"});
    const status=await res.json();
    if(!res.ok||status.ok!==true)throw new Error("readiness endpoint unavailable");
    const configured=status.owner_controls_configured===true;
    button.disabled=!configured;
    key.disabled=!configured;
    if(!configured){
      $("expSaveStatus").textContent=
        "Research results are readable. Saving changes is LOCKED because AEGIS_CONTROL_TOKEN is missing in this Vercel Preview deployment. Configure a separate 24+ character owner key in Vercel; never enter broker credentials here.";
    }
  }catch(error){
    $("expSaveStatus").textContent=
      "Cannot verify owner-control security. Saving is locked; historical Backtest and read-only Research remain available.";
  }
}
async function saveResearchSettings(){
  if(experimentSaving)return;
  const token=$("expOwnerToken").value.trim();
  $("expOwnerToken").value="";
  if(!token){
    $("expSaveStatus").textContent="Enter the separate owner control key. Never paste OANDA or Alpaca credentials.";
    return;
  }
  let data;
  try{data=selectedExperimentSettings();}
  catch(err){$("expSaveStatus").textContent=err.message;return;}
  experimentSaving=true;
  $("expSave").disabled=true;
  $("expSaveStatus").textContent="Saving verified research-only settings…";
  try{
    const res=await fetch("/api/stage3",{method:"POST",credentials:"same-origin",
      cache:"no-store",headers:{"Content-Type":"application/json",
        "Authorization":"Bearer "+token},body:JSON.stringify(data)});
    const answer=await res.json();
    if(!res.ok||answer.ok!==true)throw new Error(
      res.status===503 && answer.error==="owner_control_key_not_configured"
      ?"Set AEGIS_CONTROL_TOKEN (24+ characters) in Vercel Preview first."
      :res.status===401?"Owner key rejected; check the exact value."
      :answer.error||"Unable to save research settings.");
    experimentDirty=false;
    $("expSaveStatus").textContent="Saved in Neon ✓ · Takes effect at the next verified hourly cycle. Live orders remain OFF.";
    await pollCity();
  }catch(err){$("expSaveStatus").textContent="Not saved: "+err.message;}
  finally{experimentSaving=false;$("expSave").disabled=false;}
}

function renderBacktestChart(curve){
  const svg=$("btEquityChart");
  const values=(curve||[]).map(r=>Number(r.equity)).filter(Number.isFinite);
  if(values.length<2){svg.innerHTML="";return;}
  const min=Math.min(...values),max=Math.max(...values);
  const margin=Math.max(1,(max-min)*.07);
  const bottom=min-margin,top=max+margin;
  const path=values.map((v,i)=>{
    const x=15+870*i/(values.length-1);
    const y=223-204*(v-bottom)/(top-bottom);
    return (i?"L":"M")+x.toFixed(2)+","+y.toFixed(2);
  }).join(" ");
  const stroke=values.at(-1)>=values[0]?"#75efd1":"#fb8dcf";
  const grid=[.25,.5,.75].map(frac=>{
    const y=223-204*frac;
    return '<line x1="15" x2="885" y1="'+y+'" y2="'+y+'" stroke="#665789" stroke-opacity=".24"/>';
  }).join("");
  svg.innerHTML=grid+'<path d="'+path+'" stroke="'+stroke+'" stroke-width="2.4" fill="none" stroke-linejoin="round" vector-effect="non-scaling-stroke"/>';
}
function renderHistoricalLeaderboard(d){
  $("btResults").hidden=true;
  $("btCompareResults").hidden=false;
  $("btCompareDetails").textContent=d.strategies_tested+" strategies · "+d.asset+
    " · "+d.direction+" · "+d.interval+" · "+d.bars+" verified bars · "+
    d.holdout_bars+" OOS bars ("+fixed(d.holdout_days,2)+" calendar days). "+
    "Historical screen needs at least "+d.minimum_screen_days+" OOS days.";
  $("btCompareRows").innerHTML=(d.results||[]).map((r,i)=>{
    const ok=r.historical_screen_passed, h=r.holdout||{},sh=r.stress_holdout||{};
    const state=ok?"HISTORICAL SCREEN ONLY":"NOT QUALIFIED";
    return '<button class="strategy-rank-row" data-comparestrategy="'+safe(r.strategy)+'">'+
      '<strong class="strategy-rank-number">#'+(i+1)+'</strong>'+
      '<span class="strategy-rank-name"><strong>'+safe(r.strategy)+'</strong>'+
      '<small>'+safe(ok?"Still requires untouched forward evidence":(r.blockers||[]).join(" · "))+'</small></span>'+
      '<span class="strategy-rank-metrics"><span>OOS '+Number(h.trades||0)+' fills</span>'+
      '<span class="'+sign(h.closed_net_pnl)+'">OOS closed '+currency(h.closed_net_pnl)+'</span>'+
      '<span class="'+sign(sh.closed_net_pnl)+'">2× closed '+currency(sh.closed_net_pnl)+'</span>'+
      '<span>DD '+fixed(h.max_drawdown_pct,2)+'%</span></span>'+
      '<span class="strategy-rank-state '+(ok?"leader":"observing")+'">'+state+'</span></button>';
  }).join("");
  $("btCompareWarnings").textContent=(d.warnings||[]).join(" ");
  $("btCompareRows").querySelectorAll("[data-comparestrategy]").forEach(el=>
    el.addEventListener("click",()=>{
      $("btStrategy").value=el.dataset.comparestrategy;
      runBacktest();
    }));
}
async function compareBacktestStrategies(){
  const run=$("btRun"),btn=$("btCompare");
  if(run.disabled||btn.disabled)return;
  run.disabled=true;btn.disabled=true;
  $("btStatus").textContent="Comparing 7 strategies on the SAME closed candles and 2× cost stress…";
  const q=new URLSearchParams({
    backtest:"compare",asset:$("btAsset").value,interval:$("btInterval").value,
    direction:$("btDirection").value,cost:$("btCosts").value,
    bars:$("btBars").value});
  try{
    const res=await fetch("/api/stage3?"+q,{cache:"default"});
    const data=await res.json();
    if(!res.ok||data.ok!==true)throw new Error(data.error||"Historical comparison unavailable");
    renderHistoricalLeaderboard(data);
    $("btStatus").textContent=data.strategies_tested+
      " costed historical comparisons completed. "+data.historical_shortlist.length+
      " pass historical screening; NONE are approved for trading.";
  }catch(err){
    $("btStatus").textContent="Comparison unavailable: "+err.message;
  }finally{run.disabled=false;btn.disabled=false;}
}

function paintBacktestResult(d){
  const stats=d.full,hold=d.holdout;
  $("btResults").hidden=false;
  $("btDataSource").textContent=safe(d.source);
  $("btHeadline").innerHTML=
    '<div class="bt-metric"><small>SIMULATED NET P&L</small><strong class="'+sign(stats.net_pnl)+'">'+currency(stats.net_pnl)+'</strong></div>'+
    '<div class="bt-metric"><small>CLOSED TRADES</small><strong>'+Number(stats.trades)+'</strong></div>'+
    '<div class="bt-metric"><small>WIN RATE</small><strong>'+percent(stats.win_rate)+'</strong></div>'+
    '<div class="bt-metric"><small>MAX DRAWNDOWN</small><strong>'+fixed(stats.max_drawdown_pct,2)+'%</strong></div>'+
    '<div class="bt-metric"><small>PROFIT FACTOR</small><strong>'+fixed(stats.profit_factor,2)+'</strong></div>';
  const line=(title,x)=>'<div class="bt-comparison-row"><strong>'+title+'</strong>'+
    '<span>Net <b class="'+sign(x.net_pnl)+'">'+currency(x.net_pnl)+'</b></span>'+
    '<span>Trades <b>'+Number(x.trades)+'</b></span>'+
    '<span>Win <b>'+percent(x.win_rate)+'</b></span>'+
    '<span>PF <b>'+fixed(x.profit_factor,2)+'</b></span>'+
    '<span>Max DD <b>'+fixed(x.max_drawdown_pct,2)+'%</b></span></div>';
  $("btComparison").innerHTML=
    '<p class="bt-small-note">'+safe(d.asset)+' · '+safe(d.strategy)+' · '+safe(d.interval)+
    ' · '+safe(d.direction||"LONG")+' / '+safe(d.horizon||"INTRADAY")+
    ' · '+Number(d.bars)+' closed bars · '+utc(d.started_at)+' to '+utc(d.ended_at)+
    ' · fees '+fixed(d.risk_model?.fee_bps_each_side,1)+' bps/side'+
    ' · slippage '+fixed(d.risk_model?.slippage_bps_each_side,1)+' bps/side'+
    ' · short finance '+fixed(d.risk_model?.short_finance_bps_per_day,1)+' bps/day</p>'+
    line("FULL HISTORY",stats)+line("LAST 30% · NEW ENTRIES ONLY",hold);
  renderBacktestChart(d.equity_curve);
  $("btWarnings").innerHTML=(d.warnings||[]).map(w=>
    '<div class="bt-warning">⚠ '+safe(w)+'</div>').join("");
  $("btTrades").innerHTML=d.trades?.length?d.trades.slice().reverse().map(t=>
    '<div class="agent-trade-item bt-trade-item">'+
    '<span class="trade-state closed">'+safe(t.reason)+'</span>'+
    '<span class="trade-ledger-main"><strong>OPEN '+utc(t.entry_ts)+' → EXIT '+utc(t.exit_ts)+'</strong>'+
    '<small>Entry '+currency(t.entry_price)+' · Exit '+currency(t.exit_price)+
    ' · Qty '+fixed(t.qty,5)+' · Fee '+currency(t.fees)+
    ' · Slip '+currency(t.slippage_cost)+
    ' · Finance '+currency(t.financing_cost||0)+'</small></span>'+
    '<strong class="trade-ledger-pnl '+sign(t.net_pnl)+'">'+currency(t.net_pnl)+'</strong></div>'
  ).join(""):'<div class="await">No completed trades on this history. Do not infer profitability from an empty sample.</div>';
}
function paintWalkforwardReport(d){
  $("btWalkforwardResults").hidden=false;
  $("btWalkforwardState").textContent=(d.state||"INSUFFICIENT_EVIDENCE").replaceAll("_"," ");
  $("btWalkforwardStats").textContent=
    safe(d.asset)+" / "+safe(d.strategy)+" · "+safe(d.direction)+" · "+safe(d.interval)+
    " · "+Number(d.folds_passed||0)+"/3 folds meet research gates · "+
    Number(d.closed_trades||0)+" closed virtual trades · NO BROKER EXECUTION";
  const folds=d.folds||[];
  $("btWalkforwardFolds").innerHTML=folds.map(f=>
    '<div class="strategy-rank-row">'+
    '<strong class="strategy-rank-number">F'+Number(f.fold)+'</strong>'+
    '<span class="strategy-rank-name"><strong>'+utc(f.start)+' → '+utc(f.end)+'</strong>'+
    '<small>'+Number(f.bars)+' bars · '+fixed(f.days,2)+' days · '+
      Number(f.base.trades)+' closed trades'+
      (f.blockers.length?' · '+safe(f.blockers.join(", ")):' · Research gates met')+'</small></span>'+
    '<span class="strategy-rank-metrics">Closed net <span class="'+sign(f.base_closed_net_pnl)+'">'+
      currency(f.base_closed_net_pnl)+'</span> · 2x cost <span class="'+sign(f.stress_closed_net_pnl)+'">'+
      currency(f.stress_closed_net_pnl)+'</span></span>'+
    '<span class="strategy-rank-state '+(f.passed?'leader':'observing')+'">'+
    (f.passed?"SCREEN PASS":"INSUFFICIENT")+'</span></div>').join("");
}
async function runWalkforward(){
  const btn=$("btWalkforwardRun");
  if(btn.disabled)return;
  btn.disabled=true;
  $("btWalkforwardResults").hidden=true;
  $("btResults").hidden=true;
  $("btCompareResults").hidden=true;
  $("btStatus").textContent="Checking three chronological history windows with cost stress…";
  const params=new URLSearchParams({
    backtest:"walkforward",asset:$("btAsset").value,strategy:$("btStrategy").value,
    interval:$("btInterval").value,cost:$("btCosts").value,
    direction:$("btDirection").value,bars:$("btBars").value});
  try{
    const response=await fetch("/api/stage3?"+params.toString());
    const data=await response.json();
    if(!response.ok||data.ok!==true)
      throw new Error(data.error||("Historical verification unavailable ("+response.status+")"));
    paintWalkforwardReport(data);
    $("btStatus").textContent="Walk-forward complete: "+Number(data.folds_passed)+
      "/3 folds passed historical screens. Repeated tuning on this history is NOT independent forward proof.";
  }catch(err){
    $("btStatus").textContent="Walk-forward unavailable: "+err.message+
      ". Existing paper/demo systems were not touched.";
  }finally{btn.disabled=false;}
}

async function runBacktest(){
  const btn=$("btRun");
  if(btn.disabled)return;
  btn.disabled=true;
  $("btCompareResults").hidden=true;
  $("btResults").hidden=true;
  $("btWalkforwardResults").hidden=true;
  $("btStatus").textContent="Fetching historical closed candles and calculating costed fills…";
  const params=new URLSearchParams({
    backtest:"1",asset:$("btAsset").value,strategy:$("btStrategy").value,
    interval:$("btInterval").value,cost:$("btCosts").value,
    direction:$("btDirection").value,
    bars:$("btBars").value});
  try{
    const response=await fetch("/api/stage3?"+params.toString(),{cache:"default"});
    const body=await response.json();
    if(!response.ok||body.ok!==true)
      throw new Error(body.error||("Backtest endpoint returned "+response.status));
    paintBacktestResult(body);
    $("btStatus").textContent="Completed on source-backed historical candles. "+
      body.full.trades+" closed trades; OOS "+body.holdout.trades+
      " closed trades. No forward orders were placed.";
  }catch(err){
    $("btStatus").textContent="Backtest unavailable: "+err.message+
      ". Your existing paper trading continues separately.";
  }finally{btn.disabled=false;}
}

function paintCity(d){
  if(!isReady(d))return;
  const v=d.vault||{},workers=d.workers||[];
  $("vaultEquity").textContent=currency(v.equity);
  $("vaultDelta").textContent="Start "+currency(v.starting_equity)+" · Forward only";
  $("realizedPnl").textContent=currency(v.realized);
  $("realizedPnl").className=sign(v.realized);
  $("riskCircuit").textContent=safe(v.circuit);
  $("riskCircuit").className=v.circuit==="OPEN"?"positive":"critical";
  $("floatingVault").textContent=currency(v.realized);
  $("floatingVault").className=Number(v.realized)>=0?"positive":"negative";
  $("floatingVaultSub").textContent="Today's forward realized: "+currency(v.today);
  const marketPulse=d.last_market_monitor?.completed_at;
  $("lastRunLabel").textContent=marketPulse
    ? "MARKET PULSE VERIFIED "+utc(marketPulse)+" · 15M"
    : d.last_run?.completed_at
      ? "STRATEGY 1H VERIFIED "+utc(d.last_run.completed_at)
      : "WAITING FOR FIRST MARKET CYCLE";
  const micro=d.last_market_monitor?.summary||{};
  const source=d.last_market_monitor?.market_snapshot?.quarter_data||{};
  const unavailable=Object.entries(source).filter(([,v])=>v!=="CLOSED_15M_VERIFIED").map(([k])=>k);
  $("fastRiskPulse").textContent=marketPulse
    ? "15M CLOSED-BAR RISK · "+utc(marketPulse)+
      " · "+Number(micro.quarter_positions_reviewed||0)+" experimental paper positions checked"+
      " · "+Number(micro.quarter_exits||0)+" costed exits"+
      (unavailable.length?" · DATA DELAYED: "+unavailable.join(", "):"")+
      " · ENTRY SIGNALS: 1H · LIVE ORDERS: OFF"
    : "15M PAPER RESEARCH CHECK · Awaiting a verified monitored cycle · No live orders";
  $("positionsCount").textContent=String(d.positions?.length||0);
  $("tradesCount").textContent=String(workers.reduce((sum,w)=>sum+(Number(w.paper_trades)||0),0));
  $("ghostCount").textContent=String(Number(d.ghosts?.total||0))+" · "+String(Number(d.ghosts?.pending||0))+" pending";
  $("drawdownValue").textContent=percent(v.drawdown);
  $("eventCount").textContent=String(d.events?.length||0);
  $("stageRefresh").textContent="SNAPSHOT: "+utc(d.generated_at);
  $("cycleLabel").textContent="LAST CONFIRMED RUN · "+utc(d.last_run?.completed_at);
  makeScene(workers);
  paintEventFeed(d.events||[]);
  paintEquity(d.equity_curve||[]);
  paintPayroll(workers,d.positions||[],v);
  paintTradeTape(d.recent_trades||[],d.recent_ghosts||[]);
  paintIndividualTradeFeed(d.trade_feed||[],workers);
  paintStrategyFilterBoard(d.strategy_rankings||[]);
  paintEvolution(workers,d.evolution_events||[],d.promotion_rules||{});
  renderResearchLab(d);
  renderMicroEngine(d.micro_engine);
  renderHorizonRouter(d.research_horizon_router);
  renderDemoBrokerLedger(d.demo_brokers,d.micro_engine);
  if(currentSelection?.kind==="agent"){
    const worker=workers.find(w=>w.agent_id===currentSelection.id);
    if(worker)fillAgentDrawer(worker);
  }
  if(currentSelection?.kind==="vault")fillVaultDrawer();
}
function eventIcon(e){
  const types={PAPER_ENTRY:"↗",PAPER_EXIT:"$",ENGINE_TICK:"◉",GHOST_CREATED:"◇",ROLE_CHANGED:"♜",RISK_HALT:"⚠",GHOST_SETTLED:"✦"};
  return types[e.event_type]||"◆";
}
function paintEventFeed(events){
  const box=$("activityFeed");
  box.innerHTML=events.length?events.slice(0,14).map(e=>`
    <div class="event-row">
      <div class="event-icon ${safe(e.severity)}">${eventIcon(e)}</div>
      <div class="event-body"><strong>${safe(e.title)}</strong><small>${safe(e.description||e.scope)}</small></div>
      ${e.amount!=null?`<span class="amount ${sign(e.amount)}">${currency(e.amount)}</span>`:""}
      <time class="event-time">${utc(e.created_at)}</time>
    </div>`).join(""):'<div class="await">No event entries yet. They appear on actual hourly ticks or broker events.</div>';

  const incoming=new Set(events.map(e=>e.event_key));
  if(lastEventKeys!==null){
    const newEvents=[...events].reverse().filter(e=>!lastEventKeys.has(e.event_key));
    newEvents.slice(-4).forEach(e=>{
      toast(e);
      if(e.event_type==="PAPER_EXIT" && e.amount!=null)beamFromWorker(e);
    });
  }
  lastEventKeys=incoming;
}
function toast(event){
  const el=document.createElement("div");el.className="toast";
  const title=document.createElement("strong");title.textContent=event.title;
  const detail=document.createElement("small");detail.textContent=event.description||event.event_type;
  el.append(title,detail);$("toastHost").append(el);
  setTimeout(()=>el.remove(),5400);
}
function beamFromWorker(event){
  if(window.matchMedia("(prefers-reduced-motion: reduce)").matches)return;
  const tower=selectedTowerMap.get(event.agent_id);
  if(!tower)return;
  const {x,y}=tower,svg=$("sceneEffects");
  const path=document.createElementNS("http://www.w3.org/2000/svg","path");
  path.setAttribute("d",`M ${x} ${y-60} Q ${(x+600)/2} ${y-145} 600 428`);
  path.setAttribute("fill","none");
  path.setAttribute("class",Number(event.amount)<0?"money-beam loss-beam":"money-beam");
  svg.append(path);setTimeout(()=>path.remove(),1300);
}
function paintEquity(points){
  const svg=$("equityChart");
  $("curveRange").textContent=points.length+" VERIFIED OBSERVATIONS";
  if(!points.length){
    svg.innerHTML='<text x="270" y="63" fill="#7b81a9" text-anchor="middle" font-size="13">AWAITING FORWARD EQUITY DATA</text>';
    return;
  }
  const ys=points.map(p=>Number(p.equity||0));
  const bottom=Math.min(...ys),top=Math.max(...ys),delta=Math.max(1,top-bottom);
  const path=ys.map((v,i)=>`${i===0?"M":"L"} ${12+i*516/Math.max(1,ys.length-1)} ${109-92*(v-bottom)/delta}`).join(" ");
  const color=ys[ys.length-1]>=ys[0]?"#71e9be":"#ff7b91";
  svg.innerHTML=`<defs><linearGradient id="eqFill" x1="0" y1="0" x2="0" y2="1"><stop stop-color="${color}" stop-opacity=".20"/><stop offset="1" stop-color="${color}" stop-opacity="0"/></linearGradient></defs>
   <path d="M12 104H530M12 57H530M12 12H530" fill="none" stroke="#7167aa" stroke-opacity=".20" stroke-dasharray="3 5"/>
   <path d="${path} L 528 124 L12 124Z" fill="url(#eqFill)"/>
   <path d="${path}" fill="none" stroke="${color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
   <circle cx="${12+(ys.length-1)*516/Math.max(1,ys.length-1)}" cy="${109-92*(ys[ys.length-1]-bottom)/delta}" r="4" fill="${color}"/> `;
}

function paintPayroll(workers,positions,v){
  $("payrollTotal").textContent=currency(v.realized);
  const rows=workers.map(w=>`
    <tr data-payagent="${safe(w.agent_id)}">
      <td><span class="worker-mark"></span><strong>${symbolWorker(w)}</strong></td>
      <td>${safe(effectiveRole(w))}</td>
      <td>${w.paper_trades}</td><td>${w.paper_wins}</td>
      <td class="${sign(w.today)}">${currency(w.today)}</td>
      <td class="${sign(w.earned)}">${currency(w.earned)}</td>
    </tr>`).join("");
  $("payrollBody").innerHTML=rows||'<tr><td colspan="6">No registered paper workers yet.</td></tr>';
  $("payrollBody").querySelectorAll("[data-payagent]").forEach(el=>el.addEventListener("click",()=>showAgent(el.dataset.payagent)));
  $("positionsList").innerHTML=positions.length?positions.map(p=>`
    <div class="position-row"><span>${safe(p.symbol)} · ${safe(p.agent_id)}</span>
       <small>${fixed(p.qty,5)} units · entry ${currency(p.entry_price)}</small>
       <strong class="${sign(p.unrealized_pnl)}">${currency(p.unrealized_pnl)}</strong></div>`).join("")
    :'<div class="await">No forward paper positions are open. The engine waits for new eligible signals.</div>';
}
function paintTradeTape(trades,ghosts){
  $("cityTradeTape").innerHTML=trades.length?trades.slice(0,12).map(t=>`
    <button class="tape-item" data-tradeid="${safe(t.trade_id)}">
      <div><strong>${safe(t.symbol)} · ${safe(t.agent_id)}</strong>
        <small>${safe(t.exit_reason)} · ${utc(t.exit_ts)}</small></div>
      <span class="amount ${sign(t.net_pnl)}">${currency(t.net_pnl)}</span>
    </button>`).join("")
    :'<div class="await">No forward paper trades closed yet. The tape never imports research replay trades.</div>';
  document.querySelectorAll("[data-tradeid]").forEach(el=>el.addEventListener("click",()=>{
    const t=trades.find(x=>x.trade_id===el.dataset.tradeid);
    if(t)showTrade(t);
  }));

}
function showTrade(t){
  const html=`
    <p class="eyebrow">CLOSED PAPER TRADE · ${safe(t.trade_id)}</p>
    <h2 class="drawer-agent-symbol">${safe(t.symbol)} / LONG</h2>
    <span class="drawer-role">FORWARD VERIFIED · PAPER ONLY</span>
    <div class="drawer-huge ${sign(t.net_pnl)}">${currency(t.net_pnl)}</div>
    <p class="drawer-small">NET P&amp;L AFTER MODELED FEES</p>
    <div class="drawer-box"><h4>EXECUTION AUTOPSY</h4><div class="drawer-pairs">
      <div><span>ENTRY PRICE</span><strong>${currency(t.entry_price)}</strong></div>
      <div><span>EXIT PRICE</span><strong>${currency(t.exit_price)}</strong></div>
      <div><span>STOP</span><strong>${t.stop_price==null?"UNRECORDED":currency(t.stop_price)}</strong></div>
      <div><span>TARGET</span><strong>${t.target_price==null?"UNRECORDED":currency(t.target_price)}</strong></div>
      <div><span>QUANTITY</span><strong>${fixed(t.qty,6)}</strong></div>
      <div><span>R MULTIPLE</span><strong>${fixed(t.r_multiple,2)}R</strong></div>
      <div><span>GROSS</span><strong>${currency(t.gross_pnl)}</strong></div>
      <div><span>FEES</span><strong>${currency(t.fees)}</strong></div>
      <div><span>SLIPPAGE MODEL</span><strong>${currency(t.slippage_cost)}</strong></div>
      <div><span>EXIT REASON</span><strong>${safe(t.exit_reason)}</strong></div>
    </div></div>
    <div class="drawer-box"><h4>TRADE TIMELINE</h4><p class="drawer-small">ENTRY: ${dateTime(t.entry_ts)}<br>EXIT: ${dateTime(t.exit_ts)}<br>AGENT: ${safe(t.agent_id)}</p></div>
    <div class="drawer-box"><h4>WHY THE SYSTEM ACTED</h4>
      <p class="drawer-small">Entry: ${safe(t.order_metadata?.signal_reason||"Signal rationale was not persisted in this trade record.")}
      <br>Exit: ${safe(t.exit_reason)}
      <br>Fill model: hourly candles, estimated slippage and fees. No broker execution.</p></div>`;
  currentSelection={kind:"trade",id:t.trade_id};
  openDrawer(html,"TRADE AUTOPSY / FORWARD LEDGER");
}

function paintEvolution(workers,changes,rules){
  const active=workers.filter(w=>effectiveRole(w)==="ACTIVE_PAPER").length;
  const challengers=workers.filter(w=>["CHALLENGER","CHALLENGER_READY"].includes(effectiveRole(w))).length;
  const halted=workers.filter(w=>effectiveRole(w)==="HALTED").length;
  const eligible=workers.filter(w=>w.eligible).length;
  $("evolutionSummary").innerHTML=[
    ["PAPER INCUMBENTS",active],["CHALLENGERS",challengers],["ELIGIBLE TO REVIEW",eligible],["HALTED",halted]
  ].map(([label,n])=>`<div class="ev-metric"><span>${label}</span><strong>${n}</strong></div>`).join("");
  $("evolutionCards").innerHTML=workers.map(w=>{
    const role=effectiveRole(w),windows=w.windows||{},life=windows.lifetime||{},shadow=windows.shadow?.lifetime||{};
    const progress=Math.min(100,100*Number(w.shadow_trades||0)/(rules.min_costed_trades||40));
    return `<article class="evolution-card" tabindex="0" data-evagent="${safe(w.agent_id)}">
      <h3>${symbolWorker(w)}</h3><span class="role-tag ${statusClass(role)}">${safe(role)}</span>
      <div class="eval-stats"><div><span>FORWARD TRADES</span><strong>${w.closed_trades??0}</strong></div>
        <div><span>FORWARD DAYS</span><strong>${fixed(w.forward_days,1)}</strong></div>
        <div><span>NET P&L</span><strong class="${sign(life.net_pnl)}">${currency(life.net_pnl)}</strong></div>
        <div><span>PROFIT FACTOR</span><strong>${fixed(life.profit_factor,2)}</strong></div></div>
      <div class="shadow-figures">
        <div><span>RESEARCH PAPER TRADES</span><strong>${w.shadow_trades||0} / ${rules.min_costed_trades||40}</strong></div>
        <div><span>RESEARCH NET</span><strong class="${sign(w.shadow_net_pnl)}">${currency(w.shadow_net_pnl)}</strong></div>
        <div><span>RESEARCH PF</span><strong>${fixed(shadow.profit_factor,2)}</strong></div>
        <div><span>RESEARCH MAX DD</span><strong>${percent(w.shadow_max_drawdown)}</strong></div>
      </div>
      <div class="eval-progress"><div style="width:${progress}%"></div></div>
      <p>${safe(w.reason||"First forward evaluation pending. Paper trading remains gated.")}</p>
      </article>`;
  }).join("")||'<div class="await">No registered agents yet.</div>';
  document.querySelectorAll("[data-evagent]").forEach(el=>{
    const open=()=>showAgent(el.dataset.evagent);
    el.addEventListener("click",open);el.addEventListener("keydown",e=>{if(e.key==="Enter")open()});
  });
  $("evolutionChanges").innerHTML=changes.length?changes.map(e=>`
    <div class="event-row"><div class="event-icon">♜</div><div class="event-body"><strong>${safe(e.agent_id)} → ${safe(e.next_role)}</strong>
    <small>${safe(e.reason)} · from ${safe(e.previous_role)}</small></div><time class="event-time">${utc(e.created_at)}</time></div>`).join("")
    :'<div class="await">No role transitions verified yet. Agents are collecting forward evidence.</div>';
}

function paintEquityQuotes(data){
  const box=$("equityLiveGrid");
  const label=$("equityDataStatus");
  if(!data?.connected){
    label.textContent="NOT CONNECTED · IEX FREE DATA";
    box.innerHTML='<div class="await">Alpaca Paper Only feed is not connected yet. To display genuine SPY / QQQ / NVDA / TSLA quotes, configure ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY as Vercel server-only secrets. No real-money account needed.</div>';
    return;
  }
  label.textContent="IEX · LIMITED MARKET COVERAGE · PAPER-ONLY";
  box.innerHTML=(data.stocks||[]).map(a=>`<div class="intel-card">
    <div class="intel-top"><div><h3>${safe(a.symbol)}</h3><small>${safe(a.status)}</small></div>
      <div class="intel-score">${a.price==null?"—":currency(a.price)}<small>IEX LAST AVAILABLE TRADE</small></div></div>
    <div class="intel-details">
      <div><span>FROM PREV CLOSE</span><strong class="${sign(a.change_from_prev_close)}">${a.change_from_prev_close==null?"—":percent(a.change_from_prev_close)}</strong></div>
      <div><span>PRINT TIME</span><strong>${utc(a.last_trade_at)}</strong></div>
      <div><span>MARKET COVERAGE</span><strong>IEX ONLY</strong></div>
      <div><span>ELIGIBLE FOR ORDERS</span><strong>NO · RESEARCH</strong></div>
    </div>
    ${!a.fresh?'<div class="intel-alert">Last IEX print is stale or the market is closed. This is not a current price.</div>':""}</div>`).join("")||'<div class="await">No equity prints returned by the provider.</div>';
}
function paintPriorityMarkets(data){
  for(const [symbol,priceId,metaId] of [["BTC/USD","btcPriorityPrice","btcPriorityMeta"],["XAU/USD","goldPriorityPrice","goldPriorityMeta"]]){
    const market=(data?.markets||[]).find(m=>m.symbol===symbol);
    const price=$(priceId),meta=$(metaId);
    if(!market || typeof market.price!=="number"){
      price.textContent=symbol==="XAU/USD"?"FEED NOT CONNECTED":"DATA UNAVAILABLE";
      meta.textContent=market?.status==="WAITING_FOR_GOLD_FEED"?"Gold source not connected":
        market?.error?"Provider unavailable · no synthetic price":"Waiting for verified market feed";
      continue;
    }
    price.textContent=currency(market.price);
    const stale=market.fresh?"HOURLY SNAPSHOT":"STALE / CHECK MARKET HOURS";
    meta.textContent=stale+" · "+market.source+" · "+utc(market.observed_at);
  }
}
async function pollEquityQuotes(){
  try{
    const marketData=await fetchJson("/api/equities");
    paintPriorityMarkets({markets:marketData.priority_markets||[]});
    paintEquityQuotes(marketData);
  }catch(err){
    console.error("Market data unavailable:",err);
    paintPriorityMarkets(null);
  }
}

function paintIntelligence(data){
  if(!data?.ok){$("intelGrid").innerHTML='<div class="await">Intelligence API temporarily unavailable; no scores used for execution.</div>';return}
  $("intelGrid").innerHTML=(data.assets||[]).map(a=>{
    const sec=a.sec||{},finra=a.finra||{},ratio=finra.latest?.short_volume_ratio;
    const ratioText=ratio==null?"UNAVAILABLE":percent(ratio);
    const finraDate=finra.latest?.date||"UNKNOWN";
    const fresh=Boolean(finra.context_eligible);
    return `<div class="intel-card"><div class="intel-top"><div><h3>${safe(a.symbol)}</h3><small>${a.sources_available}/2 VERIFIED SOURCES</small></div><div class="intel-score">${fixed(a.attention_score,0)}<small>ATTENTION / 100</small></div></div>
      <div class="intel-details">
        <div><span>FINRA SHORT VOL RATIO</span><strong>${safe(ratioText)}</strong></div>
        <div><span>FINRA DATE</span><strong>${safe(finraDate)}</strong></div>
        <div><span>FLOW ANOMALY</span><strong>${fresh?fixed(finra.anomaly_score,0):"EXCLUDED"}</strong></div>
        <div><span>SEC FORM 4 / 7D</span><strong>${sec.ok?sec.counts?.form4_7d:"UNAVAILABLE"}</strong></div>
      </div>
      ${!fresh?'<div class="intel-alert">FINRA freshness gate: stale or missing input excluded from score.</div>':""}
      ${!sec.ok?'<div class="intel-alert">SEC currently unavailable from hosting environment.</div>':""}
      </div>`;
  }).join("");
}

const VIEW_IDS=Object.freeze({
  city:"cityView",payroll:"payrollView",evolution:"evolutionView",
  lab:"labView",backtest:"backtestView",intel:"intelView"
});
function viewFromHash(){
  const target=window.location.hash.slice(1).toLowerCase();
  return Object.keys(VIEW_IDS).find(key=>VIEW_IDS[key].toLowerCase()===target)||
    (Object.hasOwn(VIEW_IDS,target)?target:"city");
}
function setView(view,updateHash=true){
  if(!Object.hasOwn(VIEW_IDS,view))return;
  currentView=view;
  Object.values(VIEW_IDS).forEach(id=>$(id).classList.remove("active"));
  $(VIEW_IDS[view]).classList.add("active");
  document.querySelectorAll(".nav-tab").forEach(el=>
    el.classList.toggle("active",el.dataset.view===view));
  if(updateHash && window.location.hash!=="#"+VIEW_IDS[view]){
    window.history.replaceState(null,"","#"+VIEW_IDS[view]);
  }
  window.scrollTo({top:0,behavior:"smooth"});
}
function openDrawer(html,label){
  $("drawerEyebrow").textContent=label||"INSPECTOR / NEON DATA";
  $("drawerBody").innerHTML=html;
  $("drawerBackdrop").hidden=false;
  $("detailDrawer").classList.add("open");
  $("detailDrawer").setAttribute("aria-hidden","false");
  $("drawerClose").focus();
}
function closeDrawer(){
  $("detailDrawer").classList.remove("open");
  $("detailDrawer").setAttribute("aria-hidden","true");
  $("drawerBackdrop").hidden=true;
  currentSelection=null;
}
function fillAgentDrawer(worker){
  const role=effectiveRole(worker),pos=(cityState?.positions||[]).filter(p=>p.agent_id===worker.agent_id);
  const life=worker.windows?.lifetime||{};
  const shadow=worker.windows?.shadow?.lifetime||{};
  const html=`
    <p class="eyebrow">WORKER ID · ${safe(worker.agent_id)}</p>
    <h2 class="drawer-agent-symbol">${symbolWorker(worker)}</h2>
    <span class="drawer-role">${safe(role)}</span>
    <div class="drawer-small">One agent, one evidence trail. This is forward-paper accounting—not historical replay.</div>
    <div class="drawer-huge ${sign(worker.earned)}">${currency(worker.earned)}</div>
    <p class="drawer-small">LIFETIME REALIZED PAPER NET</p>
    <div class="drawer-box"><h4>FORWARD PAPER RECORD</h4><div class="drawer-pairs">
      <div><span>TRADES</span><strong>${worker.paper_trades}</strong></div>
      <div><span>WINS</span><strong>${worker.paper_wins}</strong></div>
      <div><span>TODAY</span><strong>${currency(worker.today)}</strong></div>
      <div><span>OOS RESEARCH RETURN</span><strong>${percent(worker.evidence?.oos_return)}</strong></div>
      <div><span>FORWARD PF</span><strong>${fixed(life.profit_factor,2)}</strong></div>
      <div><span>FORWARD DAYS</span><strong>${fixed(worker.forward_days,2)}</strong></div>
      <div><span>RISK MULTIPLIER</span><strong>${worker.risk_multiplier==null?"PENDING":fixed(worker.risk_multiplier,2)+"x"}</strong></div>
      <div><span>SURVIVAL</span><strong>${fixed(worker.survival_score,0)}/100</strong></div>
      </div></div>
    <div class="drawer-box"><h4>INDEPENDENT VIRTUAL PAPER ACCOUNT</h4>
       <p class="drawer-small">This separate virtual $100K account observes the same closed-bar signals even while Paper allocation is zero. It never places real orders.</p>
       <div class="drawer-pairs">
         <div><span>COSTED CLOSED TRADES</span><strong>${worker.shadow_trades||0}</strong></div>
         <div><span>RESEARCH NET P&L</span><strong class="${sign(worker.shadow_net_pnl)}">${currency(worker.shadow_net_pnl)}</strong></div>
         <div><span>RESEARCH POSITION</span><strong>${worker.shadow_open?"YES":"NO"}</strong></div>
         <div><span>MARKED UNREALIZED</span><strong class="${sign(worker.shadow_unrealized)}">${currency(worker.shadow_unrealized)}</strong></div>
         <div><span>MAX RESEARCH DD</span><strong>${percent(worker.shadow_max_drawdown)}</strong></div>
         <div><span>COSTED PF</span><strong>${fixed(shadow.profit_factor,2)}</strong></div>
         <div><span>7D RESEARCH NET</span><strong class="${sign(worker.shadow_week_pnl)}">${currency(worker.shadow_week_pnl)}</strong></div>
         <div><span>30D RESEARCH NET</span><strong class="${sign(worker.shadow_month_pnl)}">${currency(worker.shadow_month_pnl)}</strong></div>
       </div></div>
    <div class="drawer-box"><h4>ACTIVE POSITION</h4>${pos.length?pos.map(p=>`
      <div class="drawer-pairs"><div><span>ENTRY</span><strong>${currency(p.entry_price)}</strong></div>
      <div><span>QUANTITY</span><strong>${fixed(p.qty,5)}</strong></div>
      <div><span>STOP</span><strong>${currency(p.stop_price)}</strong></div>
      <div><span>TARGET</span><strong>${currency(p.target_price)}</strong></div></div>
      <p class="drawer-small">UNREALIZED <b class="${sign(p.unrealized_pnl)}">${currency(p.unrealized_pnl)}</b></p>`).join("")
      :'<p class="drawer-small">NO ACTIVE PAPER POSITION. Worker is observing or waiting for a fresh eligible signal.</p>'}</div>
    <div class="drawer-box"><h4>PROMOTION / DEMOTION GATE</h4>
      <div class="risk-info">${safe(worker.reason||"Awaiting first forward evidence review.")}</div>
      <p class="drawer-small">30 forward days · 40 costed trades · PF ≥ 1.30 · drawdown &lt; 5%. Ghost returns alone never permit promotion. Paper-only allocations remain subject to circuit breakers.</p>
    </div>`;
  openDrawer(html,"WORKER DOSSIER · NEON");
}
function showAgent(id){
  if(!cityState)return;
  const worker=cityState.workers?.find(w=>w.agent_id===id);
  if(!worker)return;
  currentSelection={kind:"agent",id};
  fillAgentDrawer(worker);
}
function fillVaultDrawer(){
  const v=cityState?.vault||{},curve=cityState?.equity_curve||[];
  const html=`<p class="eyebrow">THE VAULT · FORWARD ONLY</p>
    <h2 class="drawer-agent-symbol">Capital core</h2>
    <p class="drawer-small">Virtual $100,000 starting account, marked and persisted hourly.</p>
    <div class="drawer-huge">${currency(v.equity)}</div>
    <p class="drawer-small">CURRENT PAPER EQUITY</p>
    <div class="drawer-box"><h4>LEDGER BALANCES</h4>
    <div class="drawer-pairs"><div><span>START</span><strong>${currency(v.starting_equity)}</strong></div>
    <div><span>REALIZED</span><strong class="${sign(v.realized)}">${currency(v.realized)}</strong></div>
    <div><span>UNREALIZED</span><strong class="${sign(v.unrealized)}">${currency(v.unrealized)}</strong></div>
    <div><span>DRAWDOWN</span><strong>${percent(v.drawdown)}</strong></div>
    <div><span>EQUITY POINTS</span><strong>${curve.length}</strong></div>
    <div><span>CIRCUIT</span><strong>${safe(v.circuit)}</strong></div></div></div>
    <div class="drawer-box"><h4>CAPITAL FIREWALL</h4><p class="risk-info">LIVE MONEY: OFF<br>MAX RISK / TRADE: 0.25%<br>PORTFOLIO DD HALT: 5%<br>LOSS HALT / DAY: 1%<br>CONCURRENT POSITIONS: 2</p></div>`;
  openDrawer(html,"VAULT / ACCOUNT LEDGER");
}
function showVault(){currentSelection={kind:"vault"};fillVaultDrawer()}

async function fetchJson(path){
  const res=await fetch(path+(path.includes("?")?"&":"?")+"_="+Date.now(),{cache:"no-store"});
  if(!res.ok)throw new Error(path+" returned "+res.status);
  const data=await res.json();
  if(data.ok===false)throw new Error(data.error||"API returned error");
  return data;
}
async function pollCity(){
  if(livePolling)return;
  livePolling=true;
  try{
    const d=await fetchJson("/api/stage3");
    if(!isReady(d))throw new Error("Neon AEGIS ledger is not initialized; verify schema and paper account");
    cityState=d;
    paintCity(d);
    $("connectionStatus").classList.remove("down");
    $("connectionStatus").innerHTML='<span class="led"></span>NEON CONNECTED';
  }catch(err){
    console.error("Stage3 API:",err);
    $("connectionStatus").classList.add("down");
    $("connectionStatus").innerHTML='<span class="led"></span>CONNECTION LOST';
    if(!cityState)$("activityFeed").innerHTML='<div class="await">Cannot read Neon live ledger. Retrying automatically; no simulated data shown.</div>';
  }finally{livePolling=false}
}
async function pollMarket(){
  try{
    const d=await fetchJson("/api/city");
    marketState=d;
    $("marketTicker").innerHTML=(d.markets||[]).map(m=>`<span>${safe(m.symbol)}/USD <b>${currency(m.price)}</b> <em class="${sign(m.change_24h)==="positive"?"up":"down"}">${percent(m.change_24h)}</em></span>`).join("")
      +'<span>PRICE SOURCE: KRAKEN 1H CANDLES</span>';
  }catch(err){console.error("Market feed:",err);$("marketTicker").textContent="MARKET DATA DELAYED · FORWARD LEDGER CONTINUES"}
}
async function pollIntel(){
  try{intelState=await fetchJson("/api/intelligence");paintIntelligence(intelState)}
  catch(err){console.error("Intelligence feed:",err);paintIntelligence(null)}
}
function init(){
  $("btRun").addEventListener("click",runBacktest);
  $("btWalkforwardRun").addEventListener("click",runWalkforward);
  $("btCompare").addEventListener("click",compareBacktestStrategies);
  document.querySelectorAll("[data-exp-input]").forEach(el=>
    el.addEventListener("change",()=>{
      experimentDirty=true;
      $("expSaveStatus").textContent="Unsaved research settings. Enter your owner key to apply on the next research cycle.";
      $("labEngineUpdated").textContent="UNSAVED CHANGES";
    }));
  $("expSave").addEventListener("click",saveResearchSettings);
  checkResearchWriteReadiness();
  ["agentTradeFilter","tradeMarketFilter","tradeActionFilter"].forEach(id=>{
    $(id).addEventListener("change",applyTradeFilters);
  });
  const svg=$("citySvg");
  let touchStart=null;
  svg.addEventListener("pointerdown",e=>{
    if(!window.matchMedia("(max-width:620px)").matches)return;
    touchStart={x:e.clientX,cameraX:mobileCameraX,dragged:false};
  });
  svg.addEventListener("pointermove",e=>{
    if(!touchStart || !window.matchMedia("(max-width:620px)").matches)return;
    const delta=e.clientX-touchStart.x;
    if(Math.abs(delta)<8 && !touchStart.dragged)return;
    touchStart.dragged=true;
    mobileCameraX=clampCamera(touchStart.cameraX-delta*1.65);
    syncCamera();
  });
  const stopPointer=()=>{if(touchStart?.dragged)lastSceneDragAt=Date.now();touchStart=null};
  svg.addEventListener("pointerup",stopPointer);
  svg.addEventListener("pointercancel",stopPointer);
  svg.addEventListener("click",e=>{if(Date.now()-lastSceneDragAt<300){e.preventDefault();e.stopPropagation()}},true);
  window.addEventListener("resize",syncCamera);
  syncCamera();
  document.querySelectorAll(".nav-tab").forEach(el=>el.addEventListener("click",()=>setView(el.dataset.view)));
  window.addEventListener("hashchange",()=>setView(viewFromHash(),false));
  // Deep links from the Command Center must open the requested panel.
  setView(viewFromHash(),false);
  $("openPayroll").addEventListener("click",()=>setView("payroll"));
  $("eventsBtn").addEventListener("click",()=>$("activityFeed").scrollIntoView({behavior:"smooth",block:"center"}));
  $("cameraBtn").addEventListener("click",()=>{$("cityCanvas").classList.toggle("explored");$("cameraBtn").textContent=$("cityCanvas").classList.contains("explored")?"↙ DEFAULT VIEW":"↗ EXPLORE VIEW"});
  document.querySelectorAll(".scene-toggle").forEach(el=>el.addEventListener("click",()=>{
    document.querySelectorAll(".scene-toggle").forEach(item=>item.classList.toggle("selected",item===el));
    $("cityCanvas").classList.toggle("risk-layer",el.dataset.layer==="risk");
  }));
  $("sceneVault").addEventListener("click",showVault);
  $("sceneVault").addEventListener("keydown",e=>{if(e.key==="Enter")showVault()});
  $("vaultDisplay").addEventListener("click",showVault);
  $("vaultDisplay").addEventListener("keydown",e=>{if(e.key==="Enter")showVault()});
  $("drawerClose").addEventListener("click",closeDrawer);
  $("drawerBackdrop").addEventListener("click",closeDrawer);
  document.addEventListener("keydown",e=>{if(e.key==="Escape")closeDrawer()});
  $("refreshBtn").addEventListener("click",async()=>{await Promise.all([pollCity(),pollMarket(),pollIntel(),pollEquityQuotes()])});
  nowClock();setInterval(nowClock,1000);
  pollCity();pollMarket();pollIntel();pollEquityQuotes();
  setInterval(pollCity,15000);
  setInterval(pollMarket,60000);
  setInterval(pollIntel,900000);
  setInterval(pollEquityQuotes,60000);
}
init();
