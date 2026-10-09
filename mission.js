/* AEGIS Command Center: only verified Neon records are rendered.
 * An avatar represents a named research algorithm, never a conscious agent.
 * Polling is 8s; trading decisions depend on actual CLOSED OHLC events.
 */
"use strict";
const $=id=>document.getElementById(id);
const escapeHtml=v=>String(v??"").replace(/[&<>"']/g,ch=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
const usd=(v,nullable=false)=>v==null&&nullable?"—":new Intl.NumberFormat("en-US",{style:"currency",currency:"USD",maximumFractionDigits:2}).format(Number(v)||0);
const num=(v,d=2)=>Number(v||0).toLocaleString("en-US",{minimumFractionDigits:d,maximumFractionDigits:d});
const utc=v=>v?new Date(v).toLocaleString("en-GB",{timeZone:"UTC",day:"2-digit",month:"short",hour:"2-digit",minute:"2-digit",second:"2-digit"})+" UTC":"—";
const age=v=>{
  if(!v)return "غير معروف";
  const d=Math.max(0,Math.floor((Date.now()-Date.parse(v))/1000));
  if(d<60)return d+"ث";
  if(d<3600)return Math.floor(d/60)+"د";
  if(d<86400)return Math.floor(d/3600)+"س";
  return Math.floor(d/86400)+"ي";
};
const SYMBOL_COLORS=[
  ["#e6b38b","#17212d","#437d99","#62e4dc"],
  ["#b98060","#282033","#7158a0","#b3a3ff"],
  ["#f0c4a0","#262a39","#347b76","#54e1c3"],
  ["#b88a74","#151c22","#716957","#e8b875"],
  ["#d9a48c","#332131","#b25c72","#f4a4b8"],
  ["#bba27a","#18222d","#5269ad","#9dbeff"],
  ["#b47c60","#25201d","#4b8272","#86dba9"],
  ["#dbbca4","#242b44","#6c658f","#b5bbff"]
];
const AGENT_NAMES=["ATLAS","NOVA","VEGA","ORION","IRIS","ECHO","LYRA","KAI","ASTER","POLARIS","SORA","MIRA","ZENITH","ARGO","ARIA","ONYX"];
const ACTION_DESC={
  WAIT:"ما في إشارة دخول جديدة",
  MARK:"المركز تحت المراقبة",
  ENTER:"إشارة دخول ورقي مؤكدة",
  EXIT:"إغلاق مركز ورقي",
  VETO:"منع دخول لحماية المحفظة"
};
const REASONS={
  NO_FRESH_CLOSED_BAR_ENTRY:"ما ظهرت إشارة دخول جديدة على الشمعة المكتملة",
  HALTED_OR_INSUFFICIENT_CLOSED_HISTORY:"معلّق بسبب حدود المخاطرة أو نقص الشموع المتصلة",
  RISK_SIZE_VETO:"حجم المركز المطلوب تجاوز حدود المخاطرة",
  CLOSED_BAR_ENTRY_SIGNAL:"إشارة اتجاه مؤكدة من آخر شمعة مكتملة",
  CLOSED_BAR_EXIT_TRIGGER:"تم تحقق شرط الخروج من المركز الافتراضي",
  COSTED_FORWARD_STRATEGY_QUARANTINE:"استراتيجية محجورة بعد نتائج ورقية سلبية كافية",
  POSITION_MONITORED_NO_EXIT:"تمت مراقبة المركز؛ لم يتحقق وقف أو هدف أو خروج",
  SIGNAL_EXIT:"انعكاس إشارة الاستراتيجية عند إغلاق الشمعة",
  STOP:"تم الوصول إلى مستوى وقف الخسارة الافتراضي",
  TARGET:"تم الوصول إلى الهدف الافتراضي",
  STOP_AMBIGUOUS_BAR:"لامست الشمعة الوقف والهدف؛ اختير الوقف بشكل محافظ"
};
let state=null,loading=false,pollAt=null,agentRows=[],activeAction="ALL";
let knownKeys=null,lastAdded=0,currentAgent=null,connectionLost=false;
const keyOf=e=>[e.agent_id,e.bar_start,e.action].join("|");
function isValidTime(v){return typeof v==="string"&&Number.isFinite(Date.parse(v))}
function buildAvatar(index){
  const c=SYMBOL_COLORS[index%SYMBOL_COLORS.length];
  return '<div class="avatar-ring" style="--face:'+c[0]+';--hair:'+c[1]+';--coat:'+c[2]+';--agent-glow:'+c[3]+'33">'+
    '<span class="avatar-shoulders"></span><span class="avatar-neck"></span>'+
    '<span class="avatar-face"></span><span class="avatar-hair"></span>'+
    '<span class="avatar-eyes"></span><span class="avatar-headset"></span>'+
    '<span class="avatar-spark"></span></div>';
}
function displayAgentName(a,index){return AGENT_NAMES[index%AGENT_NAMES.length]}
function agentTitle(a){return a.strategy+" · "+(a.direction||"LONG")+" · "+a.interval_minutes+"m"}
function recentByAgent(journal){const map=new Map();for(const d of journal){if(!map.has(d.agent_id))map.set(d.agent_id,d)}return map}
function decodeReason(raw){return REASONS[raw]||String(raw||"قرار مسجّل بدون وصف إضافي")}
function horizonFamily(minutes){
  const n=Number(minutes);
  if(n===1||n===5)return "SCALPING";
  if(n===15||n===60)return "INTRADAY";
  if(n===240||n===1440)return "SWING";
  if(n===10080)return "POSITION";
  return "UNSUPPORTED";
}
function matchesActiveScope(row){
  const market=$("marketFilter").value;
  const direction=$("directionFilter").value;
  const horizon=$("horizonFilter").value;
  const interval=$("intervalFilter").value;
  return (market==="ALL"||row.symbol===market)&&
    (direction==="ALL"||(row.direction||"LONG")===direction)&&
    (horizon==="ALL"||horizonFamily(row.interval_minutes)===horizon)&&
    (interval==="ALL"||Number(row.interval_minutes)===Number(interval));
}
function feedConnected(micro){
  const required=micro?.required_intervals_minutes||[1,5,15];
  const channels=(micro?.sources||[]).filter(x=>required.some(n=>x.stream_name===`kraken-public-micro-${n}m`));
  const healthy=channels.filter(x=>x.state==="CONNECTED"&&isValidTime(x.updated_at)&&Date.now()-Date.parse(x.updated_at)<180000&&Date.now()>=Date.parse(x.updated_at));
  return {healthy:healthy.length,total:required.length};
}
function renderMetrics(s){
  const m=s.micro_engine||{},journal=Array.isArray(m.decision_journal)?m.decision_journal:[];
  const status=feedConnected(m);
  const connected=!connectionLost&&status.healthy===status.total&&m.is_connected===true;
  const partial=!connectionLost&&status.healthy>0&&!connected;
  const conn=$("globalConnection");
  conn.className="connection-state "+(connected?"connected":partial?"partial":"disconnected");
  conn.innerHTML='<span class="state-dot"></span>'+
    (connected?"Kraken متصل · Paper":partial?"اتصال جزئي":connectionLost?"تعذر تحديث Neon":"البيانات متأخرة / العامل متوقف");
  $("engineState").textContent=connected?"متصل":partial?"جزئي":"غير مؤكد";
  $("feedCount").textContent=status.healthy+" / "+status.total+" مصادر نشطة";
  $("crewCount").textContent=Array.isArray(m.agents)?String(m.agents.length):"—";
  $("openCount").textContent=Array.isArray(m.open_positions)?String(m.open_positions.length):"—";
  const counts=Array.isArray(m.decision_counts_last_hour)?m.decision_counts_last_hour:[];
  $("decisionsCount").textContent=m.decision_journal?String(counts.reduce((a,x)=>a+Number(x.count||0),0)):"—";
  const enter=counts.filter(x=>x.action==="ENTER").reduce((n,x)=>n+Number(x.count||0),0);
  const veto=counts.filter(x=>x.action==="VETO").reduce((n,x)=>n+Number(x.count||0),0);
  const wait=counts.filter(x=>x.action==="WAIT").reduce((n,x)=>n+Number(x.count||0),0);
  $("entryVetoCount").textContent=m.decision_journal?enter+" / "+veto:"—";
  $("entryVetoNote").textContent=m.decision_journal?
    "دخول "+enter+" · رفض "+veto+" · انتظار "+wait+" (آخر ساعة)":
    "لا توجد بيانات قرارات مؤكدة";
  const stamps=(m.bar_stats||[]).map(x=>x.last_closed_bar).filter(isValidTime);
  const mostRecent=stamps.length?stamps.sort((a,b)=>Date.parse(b)-Date.parse(a))[0]:null;
  $("lastBarAge").textContent=mostRecent?age(mostRecent):"لا يوجد";
  $("newDecisionPulse").textContent=lastAdded>0?lastAdded+" قرار جديد":journal.length+" قرار محفوظ";
  $("syncAge").textContent=pollAt?"آخر مزامنة منذ "+age(pollAt):"بانتظار قراءة Neon";
}
function renderCrew(s){
  const m=s.micro_engine||{};
  const all=Array.isArray(m.agents)?m.agents.slice():[];
  all.sort((a,b)=>String(a.symbol).localeCompare(String(b.symbol))||
      Number(a.interval_minutes)-Number(b.interval_minutes)||
      String(a.strategy).localeCompare(String(b.strategy))||
      String(a.direction||"LONG").localeCompare(String(b.direction||"LONG")));
  agentRows=all;
  const rows=all.filter(matchesActiveScope);
  $("crewFilterStatus").textContent="عرض "+rows.length+" من "+all.length+
    " وكيل ورقي · الفلاتر تتحكم بعرض الوكلاء والقرارات فقط، ولا تغيّر التداول";
  const journal=Array.isArray(m.decision_journal)?m.decision_journal:[];
  const map=recentByAgent(journal),positions=new Map((m.open_positions||[]).map(p=>[p.agent_id,p]));
  $("crewGrid").innerHTML=rows.length?rows.map(a=>{
    const index=all.findIndex(x=>x.agent_id===a.agent_id);
    const name=displayAgentName(a,index);
    const d=map.get(a.agent_id);
    const action=d?.action||"AWAITING";
    const ageLabel=d?"آخر قرار "+age(d.observed_at||d.bar_start)+" · "+utc(d.bar_start):"بانتظار قرار موثّق";
    const held=positions.has(a.agent_id);
    return '<button type="button" class="crew-card '+escapeHtml(action.toLowerCase())+
      '" data-agent="'+escapeHtml(a.agent_id)+'" aria-label="تفاصيل الوكيل '+escapeHtml(name)+'">'+
      '<div class="crew-eyebrow"><span>'+escapeHtml(a.symbol)+' · '+Number(a.interval_minutes)+'M</span>'+
      '<span class="crew-status-icon">'+(held?"● POSITION":"○ OBSERVE")+'</span></div>'+
      buildAvatar(index)+'<h3>'+escapeHtml(name)+'</h3>'+
      '<div class="crew-subtitle">'+escapeHtml(a.strategy)+' · '+escapeHtml(a.direction||"LONG")+'</div>'+
      '<div class="crew-decision"><span class="action">'+escapeHtml(action)+'</span>'+
      '<span>·</span><span>'+escapeHtml(d?decodeReason(d.reason).slice(0,24):"لا يوجد حدث بعد")+'</span></div>'+
      '<div class="crew-when">'+escapeHtml(ageLabel)+'</div></button>';
  }).join(""):'<div class="empty-state">ما في وكلاء Micro مسجلين لهذا السوق. ما رح نخترع شخصيات أو تداولات.</div>';
}
function renderTimeline(s){
  const m=s.micro_engine||{},raw=m.decision_journal;
  if(!Array.isArray(raw)){
    $("decisionFeed").innerHTML='<div class="empty-state">واجهة API الحالية لا تعرض سجل القرارات بعد. بانتظار تفعيل الإصدار الجديد، وما في بيانات مصطنعة.</div>';
    $("feedTail").textContent="سجل القرارات غير متاح في النسخة المنشورة حاليًا";
    return;
  }
  const journal=raw.filter(d=>(activeAction==="ALL"||d.action===activeAction)&&
    matchesActiveScope(d));
  const labels={ENTER:"↗",EXIT:"↘",WAIT:"◷",MARK:"◎",VETO:"⊘"};
  $("decisionFeed").innerHTML=journal.length?journal.map(d=>
    '<article class="decision-event '+escapeHtml(String(d.action).toLowerCase())+'">'+
    '<div class="event-icon" aria-hidden="true">'+(labels[d.action]||"●")+'</div>'+
    '<div class="event-body"><div class="event-head">'+
    '<strong>'+escapeHtml(d.symbol)+' · '+escapeHtml(d.strategy)+
    ' · '+escapeHtml(d.direction)+' · '+Number(d.interval_minutes)+'m</strong>'+
    '<small>'+escapeHtml(age(d.observed_at))+'</small></div>'+
    '<div class="event-reason"><span class="event-action">'+escapeHtml(d.action)+
    '</span> — '+escapeHtml(decodeReason(d.reason))+'</div>'+
    '<div class="event-foot"><span>شمعة '+escapeHtml(utc(d.bar_start))+'</span>'+
    '<span>سعر '+usd(d.reference_price,true)+'</span>'+
    (d.qty!=null?'<span>كمية '+num(d.qty,6)+'</span>':"")+
    (d.net_pnl!=null?'<span>صافي ورقي '+usd(d.net_pnl)+'</span>':"")+
    '</div></div></article>').join(""):
    '<div class="empty-state">لا يوجد قرار '+(activeAction==="ALL"?"مسجّل حتى الآن":"بهذا النوع ضمن آخر 160 حدثًا")+'. سنعرض فقط الأحداث الموثقة من المحرك.</div>';
  $("feedTail").textContent="قرارات مطابقة للفلترة: "+journal.length+
    " من "+raw.length+" سجل موثّق · التحديث كل 8 ثوانٍ · الصفقات افتراضية فقط";
}
function renderDemo(s){
  const a=s.demo_brokers?.connected_accounts||[];
  const provider=id=>a.find(x=>x.provider===id);
  const g=provider("MT5_DEMO");
  const m=s.micro_engine||{};
  const btcAgents=(m.agents||[]).filter(x=>x.symbol==="BTC");
  const active=(m.active_intervals_minutes||[]).length;
  const btcStatus=connectionLost?"تعذّر تحديث الحالة":btcAgents.length&&active>0?"Paper · "+active+" فواصل نشطة":btcAgents.length?"Paper · انتظار مصادر Kraken":"Paper · بانتظار تهيئة الوكلاء";
  const status=v=>!v?"غير مرتبط":!connectionLost&&v.sync_status==="SYNCED_DEMO"&&isValidTime(v.last_synced)&&Date.now()-Date.parse(v.last_synced)<300000?"Demo متصل · قراءة فقط":"مزامنة متأخرة";
  $("demoStatus").innerHTML='<span>MT5 GOLD</span><strong>'+escapeHtml(status(g))+'</strong>'+
    '<span>BTC PAPER</span><strong>'+escapeHtml(btcStatus)+'</strong>';
  const router=s.research_horizon_router||{};
  const selected=router.selected;
  $("horizonSummary").textContent=selected?
    "أقوى دليل مرصود: "+selected.horizon+" · "+selected.interval+
    " · "+selected.direction+" · "+selected.trades+" صفقة مغلقة (بحث فقط)":
    "لا توجد أفضلية مثبتة بعد. نحتاج نتائج Forward مغلقة كافية، ولا نمنح صلاحية تداول تلقائي.";
}
function trackNewEvents(s){
  const events=s.micro_engine?.decision_journal;
  if(!Array.isArray(events)){lastAdded=0;return;}
  const current=new Set(events.map(keyOf));
  if(knownKeys===null){lastAdded=0;knownKeys=current;return;}
  lastAdded=events.filter(e=>!knownKeys.has(keyOf(e))).length;
  knownKeys=current;
}
function render(){
  if(!state)return;
  renderMetrics(state);
  renderCrew(state);
  renderTimeline(state);
  renderDemo(state);
  renderHorizonEvidence(state);
  renderBrokerFills(state);
  if(currentAgent&&$("agentOverlay").hidden===false)renderDossier(currentAgent);
}
async function poll(){
  if(loading)return;
  loading=true;
  try{
    const res=await fetch("/api/stage3",{cache:"no-store",headers:{"Accept":"application/json"}});
    if(!res.ok)throw Error("Ledger API "+res.status);
    const d=await res.json();
    if(d.ok!==true||d.initialized!==true)throw Error("Ledger not ready");
    state=d;pollAt=new Date().toISOString();connectionLost=false;
    trackNewEvents(d);render();
  }catch(error){
    connectionLost=true;lastAdded=0;
    if(state)renderMetrics(state);
    else{
      $("globalConnection").className="connection-state disconnected";
      $("globalConnection").textContent="تعذر الاتصال بسجل Neon";
      $("decisionFeed").innerHTML='<div class="empty-state">تعذر جلب القرارات الموثقة من Neon. سنعيد المحاولة تلقائيًا، دون أرقام وهمية.</div>';
      $("crewGrid").innerHTML='<div class="empty-state">حالة فريق AEGIS غير متاحة مؤقتًا.</div>';
    }
  }finally{loading=false}
}
function renderDossier(id){
  const m=state?.micro_engine||{},a=agentRows.find(x=>x.agent_id===id);
  if(!a){$("agentDialogContent").innerHTML='<div class="empty-state">الوكيل غير موجود في آخر سجل Neon.</div>';return;}
  const i=agentRows.findIndex(x=>x.agent_id===id);
  const positions=m.open_positions||[],pos=positions.find(x=>x.agent_id===id);
  const recent=(m.decision_journal||[]).filter(x=>x.agent_id===id).slice(0,18);
  const line=(heading,value)=>'<div><small>'+heading+'</small><strong>'+escapeHtml(value)+'</strong></div>';
  $("agentDialogContent").innerHTML='<div class="dossier-header">'+buildAvatar(i)+
    '<div><h2 id="agentDialogTitle">'+escapeHtml(displayAgentName(a,i))+'</h2>'+
    '<p>'+escapeHtml(agentTitle(a))+' · '+escapeHtml(a.symbol)+'</p></div></div>'+
    '<div class="dossier-info">'+
    line("الرصيد الورقي",usd(a.cash))+
    line("التراجع الأقصى",num(Number(a.max_drawdown||0)*100,2)+"%")+
    line("المركز الحالي",pos?escapeHtml(pos.direction)+" · "+usd(pos.entry_price):"لا يوجد")+
    line("حالة المخاطرة",a.halted?"HALTED · ممنوع دخول جديد":"RESEARCH · PAPER")+
    '</div><h3 class="dossier-title">آخر القرارات المسجلة لهذا الوكيل</h3>'+
    (recent.length?recent.map(d=>'<div class="dossier-event"><strong>'+escapeHtml(d.action)+
      '</strong> · '+escapeHtml(decodeReason(d.reason))+'<div><time>'+escapeHtml(utc(d.bar_start))+
      ' · '+usd(d.reference_price,true)+'</time></div></div>').join(""):
    '<div class="empty-state">بانتظار أول قرار موثق لهذا الوكيل.</div>');
}
function openDossier(id){currentAgent=id;renderDossier(id);$("agentOverlay").hidden=false;document.body.style.overflow="hidden";$("closeAgent").focus()}
function closeDossier(){$("agentOverlay").hidden=true;document.body.style.overflow="";currentAgent=null}
document.addEventListener("click",e=>{
  const el=e.target.closest("[data-agent]");
  if(el){openDossier(el.dataset.agent);return}
  const filter=e.target.closest("[data-action]");
  if(filter){
    activeAction=filter.dataset.action;
    document.querySelectorAll("[data-action]").forEach(x=>x.classList.toggle("active",x===filter));
    if(state)renderTimeline(state);
  }
});
["marketFilter","directionFilter","horizonFilter","intervalFilter"].forEach(id=>
  $(id).addEventListener("change",()=>{
    if(state){renderCrew(state);renderTimeline(state);}
  }));
$("forceRefresh").addEventListener("click",poll);
$("closeAgent").addEventListener("click",closeDossier);
$("agentOverlay").addEventListener("click",e=>{if(e.target===$("agentOverlay"))closeDossier()});
document.addEventListener("keydown",e=>{if(e.key==="Escape")closeDossier()});
function tickClock(){
  $("feedClock").textContent=new Date().toLocaleTimeString("en-GB",{hour12:false,timeZone:"UTC"})+" UTC";
  if(state){renderMetrics(state);renderDemo(state);renderHorizonEvidence(state);}
}
tickClock();setInterval(tickClock,1000);
poll();setInterval(()=>{if(!document.hidden)poll()},8000);
document.addEventListener("visibilitychange",()=>{if(!document.hidden)poll()});

const horizonRows=[[1,'1min','سكالبينغ'],[5,'5min','سكالبينغ'],[15,'15min','يومي'],[60,'1h','يومي'],[240,'4h','سوينغ'],[1440,'1day','سوينغ'],[10080,'1week','أسبوعي']];
function renderHorizonEvidence(s){
  const m=s.micro_engine||{},r=s.research_horizon_router||{};
  $('horizonEvidence').innerHTML=horizonRows.map(([minutes,label,family])=>{
    const feed=(m.sources||[]).find(f=>f.stream_name===`kraken-public-micro-${minutes}m`);
    const active=!connectionLost&&(m.active_intervals_minutes||[]).includes(minutes)&&feed&&isValidTime(feed.updated_at)&&Date.now()-Date.parse(feed.updated_at)<180000;
    const agents=(m.agents||[]).filter(a=>a.interval_minutes===minutes);
    const candidates=(r.candidates||[]).filter(c=>c.interval===label);
    const screens=(r.historical_screens||[]).filter(c=>c.interval===label);
    const n=candidates.reduce((a,c)=>a+c.trades,0);
    return '<tr><td>'+label+' · '+family+'</td><td>'+(active?'متصل':'غير مؤكد')+'</td><td>'+agents.filter(a=>a.direction==='LONG').length+' / '+agents.filter(a=>a.direction==='SHORT').length+'</td><td>'+n+'</td><td>'+screens.filter(c=>c.historical_screen_passed).length+' / '+screens.length+'</td><td>'+(candidates.some(c=>c.selection_qualified)?'مؤهل بحثيًا':'أدلة غير كافية')+'</td></tr>';
  }).join('');
}
function renderBrokerFills(s){
  const fills=s.demo_brokers?.recent_fills||[];
  $('brokerFills').innerHTML=fills.length?fills.slice(0,12).map(f=>'<tr><td>'+escapeHtml(f.provider||f.source_id)+'</td><td>'+escapeHtml(f.symbol)+'</td><td>'+escapeHtml(f.side)+'</td><td>'+num(f.qty,6)+'</td><td>'+usd(f.price,true)+'</td><td>'+escapeHtml(utc(f.executed_at))+'</td></tr>').join(''):'<tr><td colspan="6">لا توجد تنفيذات Demo متزامنة. Bitcoin Spot Demo لا يدعم فتح Short؛ نتائج Short الحالية محاكاة فقط.</td></tr>';
}
let comparingHorizons=false;
async function compareHorizons(){
  if(comparingHorizons)return;
  comparingHorizons=true;
  const btn=$('compareHorizons');btn.disabled=true;
  const asset=$('comparisonAsset').value;
  $('horizonCompareRows').innerHTML='';
  try{
    for(const [,interval] of horizonRows){
      $('horizonCompareStatus').textContent='فحص '+asset+' / '+interval+' · Long وShort منفصلان…';
      const q=new URLSearchParams({backtest:'horizon',asset,interval,bars:'720',cost:'base'});
      try{
        const res=await fetch('/api/stage3?'+q,{signal:AbortSignal.timeout(45000)});
        const data=await res.json();
        if(!res.ok||!data.ok)throw Error(data.error||'المصدر غير متاح');
        for(const report of data.reports){
          for(const row of report.results){
            const h=row.holdout,stress=row.stress_holdout;
            $('horizonCompareRows').insertAdjacentHTML('beforeend','<tr><td>'+escapeHtml(interval)+'</td><td>'+escapeHtml(report.direction)+'</td><td>'+escapeHtml(row.strategy)+'</td><td>'+num(report.holdout_days)+'</td><td>'+h.trades+'</td><td>'+usd(h.closed_net_pnl)+'</td><td>'+usd(stress.closed_net_pnl)+'</td><td>'+num(h.max_drawdown_pct)+'%</td><td>'+escapeHtml(row.historical_screen_passed?'اجتاز التاريخي فقط':row.blockers.join(' · '))+'</td></tr>');
          }
        }
      }catch(error){
        $('horizonCompareRows').insertAdjacentHTML('beforeend','<tr><td>'+escapeHtml(interval)+'</td><td colspan="8">غير متاح: '+escapeHtml(error.message)+'</td></tr>');
      }
    }
    $('horizonCompareStatus').textContent='اكتمل الفحص. الفترات التاريخية متفاوتة؛ لا نعلن فائزًا شاملًا ولا نفعّل تداولًا. النتائج التاريخية لا تدخل سجل Forward.';
  }finally{btn.disabled=false;comparingHorizons=false;}
}
$('compareHorizons').addEventListener('click',compareHorizons);
