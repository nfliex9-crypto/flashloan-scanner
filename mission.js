/* AEGIS / concise trading bot terminal.
 * Only real persisted Neon Paper receipts and broker-confirmed Demo ledgers.
 * No client-side strategy generation, order submission, broker credentials or false PnL.
 */
"use strict";
const $ = id => document.getElementById(id);
const esc = v => String(v ?? "").replace(/[&<>"']/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const money = v => v == null ? "—" :
  new Intl.NumberFormat("en-US",{style:"currency",currency:"USD",maximumFractionDigits:2}).format(Number(v));
const num = (v,n=2) => Number(v||0).toLocaleString("en-US",{maximumFractionDigits:n});
const stamp = v => v ? new Date(v).toLocaleString("ar-BE",{timeZone:"UTC"})+" UTC" : "—";
const INTERVALS = [1,5,15,60,240,1440,10080];
let snapshot=null, syncing=false;
const statusNames={
  HALTED_RISK:"متوقف · حدود الحساب",FEED_UNVERIFIED:"المصدر غير مؤكد",
  OPEN_PAPER_POSITION:"صفقة Paper مفتوحة",COLLECTING_FORWARD:"يجمع نتائج",
  PAPER_OBSERVING:"يبحث عن فرصة"
};

function botScope(bot){
  return ($("botFleetStrategy").value==="ALL"||bot.strategy===$("botFleetStrategy").value)&&
    ($("botFleetDirection").value==="ALL"||bot.direction===$("botFleetDirection").value)&&
    ($("botFleetPeriod").value==="ALL"||String(bot.interval_minutes)===$("botFleetPeriod").value);
}
function renderBotFleet(d){
  const all=Array.isArray(d.micro_engine?.paper_bots)?d.micro_engine.paper_bots:null;
  const table=$("botFleetRows");
  if(!all){
    table.innerHTML='<tr><td colspan="8">نسخة API هذه لا تعرض سجلات البوتات بعد. لا أرقام مصطنعة.</td></tr>';
    $("botFleetCount").textContent="بانتظار API Bot Fleet";
    return;
  }
  const scoped=all.filter(botScope);
  $("botFleetCount").textContent=scoped.length+" / "+all.length+" بوت Paper";
  table.innerHTML=scoped.length?scoped.map(b=>{
    const label=esc(b.strategy)+" · "+esc(b.direction);
    const net=b.net_pnl_after_costs;
    const avg=b.average_net_per_closed_trade;
    const positive=Number(net)>0;
    const q=b.oos_forward_qualified===true?"اجتاز الأدلة":"غير مؤهل بعد";
    return '<tr>'+
      '<td><strong>'+label+'</strong><small>'+esc(b.asset||"BTC")+' · '+esc(b.bot_id)+'</small></td>'+
      '<td>'+num(b.interval_minutes,0)+'m</td>'+
      '<td><span class="bot-status" data-state="'+esc(b.state)+'">'+esc(statusNames[b.state]||"غير مؤكد")+'</span></td>'+
      '<td>'+num(b.closed_trades,0)+'</td>'+
      '<td class="'+(positive?"profit":"loss")+'">'+money(net)+'</td>'+
      '<td>'+money(avg)+'</td>'+
      '<td>'+(b.profit_factor==null?"—":num(b.profit_factor))+'</td>'+
      '<td>'+(b.oos_forward_qualified===true?'<span class="bot-qualified">'+q+'</span>':esc(q))+'</td>'+
      '</tr>';
  }).join(""):'<tr><td colspan="8">لا توجد بوتات مطابقة لهذه الفلاتر.</td></tr>';
  const complete=all.filter(b=>b.closed_trades>0);
  $("botFleetFootnote").textContent=
    complete.length+" بوت لديه صفقات Paper مغلقة · المقاييس من نتائج Kraken Forward بعد التكاليف · "+
    "ربح بوت في الماضي لا يثبت أفضلية مستقبلية.";
}
function renderDecisions(d){
  const tape=d.micro_engine?.decision_journal;
  if(!Array.isArray(tape)){
    $("decisionFeed").innerHTML='<div class="empty-state">سجل قرارات Paper غير متاح.</div>';
    return;
  }
  const items=tape.slice(0,22);
  const act={ENTER:"فتح Paper",EXIT:"إغلاق Paper",WAIT:"انتظار",
             VETO:"رفض",MARK:"مراقبة"};
  $("decisionFeed").innerHTML=items.length?items.map(e=>
    '<div class="bot-event"><span class="bot-event-action" data-action="'+esc(e.action)+'">'+
    esc(act[e.action]||e.action)+'</span><strong>'+esc(e.symbol)+' · '+esc(e.strategy)+
    ' · '+esc(e.direction)+' · '+num(e.interval_minutes,0)+'m</strong>'+
    '<small>'+esc(stamp(e.observed_at||e.bar_start))+'</small></div>'
  ).join(""):'<div class="empty-state">لا توجد قرارات موثقة بعد.</div>';
  $("decisionCount").textContent=tape.length+" قرارًا مسجّلًا";
}
function renderTop(d){
  const micro=d.micro_engine||{};
  const online=Array.isArray(micro.active_intervals_minutes)?
    micro.active_intervals_minutes.filter(n=>INTERVALS.includes(n)).length:0;
  $("globalConnection").textContent=online?
    "Kraken Paper · "+online+" / 7 مصادر":"المصدر غير مؤكد";
  $("globalConnection").dataset.state=online?"PARTIAL":"UNVERIFIED";
  $("feedCount").textContent=online+" / 7";
  $("openCount").textContent=Array.isArray(micro.open_positions)?
    String(micro.open_positions.length):"—";
  $("decisionsCount").textContent=Array.isArray(micro.decision_journal)?
    String(micro.decision_journal.length):"—";
  $("botCount").textContent=Array.isArray(micro.paper_bots)?
    String(micro.paper_bots.length):"—";
  const gold=(d.demo_brokers?.connected_accounts||[]).find(a=>a.provider==="MT5_DEMO");
  const goldFresh=gold?.sync_status==="SYNCED_DEMO" && gold.last_synced &&
    Number.isFinite(Date.parse(gold.last_synced))&&Date.now()-Date.parse(gold.last_synced)<300000;
  $("demoStatus").textContent=goldFresh?
    "MT5 Demo · "+esc(gold.market||"XAUUSD")+" · آخر مزامنة "+stamp(gold.last_synced):
    "الذهب: غير متصل أو سجل قديم · Bitcoin: Paper";
  $("lastUpdated").textContent="آخر قراءة: "+new Date().toLocaleTimeString("ar-BE");
}
function render(d){renderTop(d);renderBotFleet(d);renderDecisions(d);}
async function refreshLedger(){
  if(syncing)return;
  syncing=true;
  $("refreshMain").disabled=true;
  try{
    const res=await fetch("/api/stage3",{cache:"no-store",headers:{"Accept":"application/json"}});
    if(!res.ok)throw Error("api_not_ready");
    const d=await res.json();
    if(d.ok!==true||d.initialized!==true)throw Error("ledger_not_ready");
    snapshot=d;
    render(d);
  }catch(e){
    $("globalConnection").textContent="لا يوجد اتصال موثّق بـNeon";
    $("globalConnection").dataset.state="UNVERIFIED";
    $("lastUpdated").textContent="تعذّر تحديث السجل";
    // Never keep stale account metrics looking current during database errors.
    $("botCount").textContent="—";
    $("openCount").textContent="—";
    $("decisionsCount").textContent="—";
    $("feedCount").textContent="—";
    $("botFleetCount").textContent="بانتظار بيانات حقيقية";
    $("botFleetRows").innerHTML='<tr><td colspan="8">تعذر قراءة Paper من Neon؛ جرّب تحديث البيانات.</td></tr>';
    $("decisionFeed").innerHTML='<div class="empty-state">تعذر جلب سجل الصفقات الحقيقي.</div>';
    $("demoStatus").textContent="حالة MT5 Demo غير مؤكدة";
    snapshot=null;
  }finally{
    syncing=false;
    $("refreshMain").disabled=false;
  }
}
["botFleetStrategy","botFleetDirection","botFleetPeriod"].forEach(id=>
  $(id).addEventListener("change",()=>{if(snapshot)renderBotFleet(snapshot);}));
$("refreshMain").addEventListener("click",refreshLedger);
refreshLedger();
window.setInterval(()=>{if(!document.hidden)refreshLedger()},12000);
