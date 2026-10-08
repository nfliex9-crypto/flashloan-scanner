/* AEGIS Agent City 3.0: every financial datum is sourced from Neon. */
const $ = (id) => document.getElementById(id);
const currency = (n) => new Intl.NumberFormat("en-US",{style:"currency",currency:"USD",maximumFractionDigits:2}).format(Number(n)||0);
const fixed = (v,d=2) => Number(v||0).toFixed(d);
const percent = (v,d=2) => fixed(100*Number(v||0),d)+"%";
const sign = (v) => Number(v||0)>=0?"positive":"negative";
const safe = (v) => String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const utc = (v) => v ? new Date(v).toLocaleString("en-GB",{month:"short",day:"2-digit",hour:"2-digit",minute:"2-digit",timeZone:"UTC"})+" UTC" : "—";
const dateTime = (v) => v ? new Date(v).toLocaleString("en-GB",{timeZone:"UTC"})+" UTC" : "—";
let cityState=null,marketState=null,intelState=null;
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
  let remaining;
  if(utcMin < 5){remaining=(5-utcMin)*60-utcSec;}
  else{remaining=(65-utcMin)*60-utcSec;}
  const mm=Math.floor(Math.max(0,remaining)/60),ss=Math.max(0,remaining)%60;
  $("nextScan").textContent=String(mm).padStart(2,"0")+":"+String(ss).padStart(2,"0");
}
function makeScene(workers){
  const byAsset={BTC:[],ETH:[]};
  workers.forEach(w=>{if(byAsset[w.asset])byAsset[w.asset].push(w)});
  byAsset.BTC.sort((a,b)=>a.strategy.localeCompare(b.strategy));
  byAsset.ETH.sort((a,b)=>a.strategy.localeCompare(b.strategy));
  const arranged=[...byAsset.BTC,...byAsset.ETH];
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
  const active=arranged.filter(w=>w.status==="ACTIVE" && (effectiveRole(w)==="ACTIVE_PAPER"||effectiveRole(w)==="RESEARCH_ACTIVE")).length;
  $("activeWorkers").textContent=String(active)+" / "+arranged.length;
  $("onShiftDetails").textContent="Paper-eligible research incumbents";
  $("quickWorkers").innerHTML=arranged.map(w=>`<button class="worker-chip ${statusClass(effectiveRole(w))}" data-quickagent="${safe(w.agent_id)}">
    <strong>${symbolWorker(w)}</strong><small>${safe(effectiveRole(w))} · ${currency(w.earned)}</small></button>`).join("");
  document.querySelectorAll("[data-quickagent]").forEach(el=>el.addEventListener("click",()=>showAgent(el.dataset.quickagent)));
  syncCamera();
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
  $("lastRunLabel").textContent=d.last_run?.completed_at?"ENGINE VERIFIED "+utc(d.last_run.completed_at):"WAITING FOR FIRST RUN";
  $("positionsCount").textContent=String(d.positions?.length||0);
  $("tradesCount").textContent=String(workers.reduce((sum,w)=>sum+(Number(w.paper_trades)||0),0));
  $("ghostCount").textContent=String(Number(d.ghosts?.total||0))+" · "+String(Number(d.ghosts?.pending||0))+" pending";
  $("shadowCostedCount").textContent=String(d.shadow_costed_trades||0);
  $("shadowOpenCount").textContent=String(d.shadow_open_positions||0);
  $("drawdownValue").textContent=percent(v.drawdown);
  $("eventCount").textContent=String(d.events?.length||0);
  $("stageRefresh").textContent="SNAPSHOT: "+utc(d.generated_at);
  $("cycleLabel").textContent="LAST CONFIRMED RUN · "+utc(d.last_run?.completed_at);
  makeScene(workers);
  paintEventFeed(d.events||[]);
  paintEquity(d.equity_curve||[]);
  paintPayroll(workers,d.positions||[],v);
  paintTradeTape(d.recent_trades||[],d.recent_ghosts||[]);
  paintEvolution(workers,d.evolution_events||[],d.promotion_rules||{});
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
  $("cityGhostLab").innerHTML=ghosts.length?ghosts.slice(0,12).map(g=>`
    <div class="ghost-item"><div><strong>${safe(g.symbol)} · ${safe(g.agent_id)}</strong>
      <small>${safe(g.reason)} · ${utc(g.signal_ts)}</small></div>
      <span class="${g.settled_at?'amount '+sign(g.forward_return):'pending'}">${g.settled_at?percent(g.forward_return):"PENDING 12H"}</span>
    </div>`).join("")
    :'<div class="await">No ghost signals recorded yet. Rejected signals will settle only after future market data exists.</div>';
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
        <div><span>SHADOW COSTED TRADES</span><strong>${w.shadow_trades||0} / ${rules.min_costed_trades||40}</strong></div>
        <div><span>SHADOW NET</span><strong class="${sign(w.shadow_net_pnl)}">${currency(w.shadow_net_pnl)}</strong></div>
        <div><span>SHADOW PF</span><strong>${fixed(shadow.profit_factor,2)}</strong></div>
        <div><span>SHADOW MAX DD</span><strong>${percent(w.shadow_max_drawdown)}</strong></div>
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

function setView(view){
  const names={city:"cityView",payroll:"payrollView",evolution:"evolutionView",intel:"intelView"};
  if(!names[view])return;
  currentView=view;
  Object.values(names).forEach(id=>$(id).classList.remove("active"));
  $(names[view]).classList.add("active");
  document.querySelectorAll(".nav-tab").forEach(el=>el.classList.toggle("active",el.dataset.view===view));
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
    <div class="drawer-box"><h4>INDEPENDENT COSTED SHADOW ACCOUNT</h4>
       <p class="drawer-small">This separate virtual $100K account observes the same closed-bar signals even while Paper allocation is zero. It never places real orders.</p>
       <div class="drawer-pairs">
         <div><span>COSTED CLOSED TRADES</span><strong>${worker.shadow_trades||0}</strong></div>
         <div><span>SHADOW NET P&L</span><strong class="${sign(worker.shadow_net_pnl)}">${currency(worker.shadow_net_pnl)}</strong></div>
         <div><span>SHADOW OPEN</span><strong>${worker.shadow_open?"YES":"NO"}</strong></div>
         <div><span>MARKED UNREALIZED</span><strong class="${sign(worker.shadow_unrealized)}">${currency(worker.shadow_unrealized)}</strong></div>
         <div><span>MAX SHADOW DD</span><strong>${percent(worker.shadow_max_drawdown)}</strong></div>
         <div><span>COSTED PF</span><strong>${fixed(shadow.profit_factor,2)}</strong></div>
         <div><span>7D SHADOW NET</span><strong class="${sign(worker.shadow_week_pnl)}">${currency(worker.shadow_week_pnl)}</strong></div>
         <div><span>30D SHADOW NET</span><strong class="${sign(worker.shadow_month_pnl)}">${currency(worker.shadow_month_pnl)}</strong></div>
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
  $("refreshBtn").addEventListener("click",async()=>{await Promise.all([pollCity(),pollMarket(),pollIntel()])});
  nowClock();setInterval(nowClock,1000);
  pollCity();pollMarket();pollIntel();
  setInterval(pollCity,15000);
  setInterval(pollMarket,60000);
  setInterval(pollIntel,900000);
}
init();
