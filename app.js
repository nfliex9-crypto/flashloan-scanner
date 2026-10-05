const $ = (id) => document.getElementById(id);

const money = (v) => new Intl.NumberFormat("en-US",{style:"currency",currency:"USD",maximumFractionDigits:2}).format(Number(v));
const pct = (v,d=2) => (Number(v)*100).toFixed(d)+"%";
const num = (v,d=2) => Number(v).toFixed(d);

function empty(text){ return '<div class="empty">'+text+'</div>'; }

function marketCard(m){
  const cls = m.change_24h >= 0 ? "up" : "down";
  const closed = m.last_candle_utc ? new Date(m.last_candle_utc).toLocaleTimeString("en-GB",{hour:"2-digit",minute:"2-digit"}) : "—";
  return `
    <article class="market-card">
      <div class="market-top">
        <div><span class="symbol">${m.symbol}/USD</span><div class="delta ${cls}">${pct(m.change_24h)}</div></div>
        <div class="price">${money(m.price)}</div>
      </div>
      <div class="market-meta">
        <div><span>7D Return</span><strong>${pct(m.change_7d)}</strong></div>
        <div><span>Annualized Vol</span><strong>${pct(m.annualized_volatility)}</strong></div>
        <div><span>Regime</span><strong class="regime">${m.regime}</strong></div>
        <div><span>Closed bar</span><strong>${closed}</strong></div>
      </div>
    </article>`;
}

function tfBadges(a){
  const rows = Object.entries(a.timeframe_evidence || {});
  if(!rows.length) return "";
  return '<div class="tf-row">'+rows.map(([name,e])=>{
    const ok = e.oos_return > 0 && e.stress_passes >= 3;
    return `<span class="tf-badge ${ok?'tf-pass':'tf-fail'}">${name} ${ok?'✓':'×'}</span>`;
  }).join("")+'</div>';
}

function agentCard(a){
  return `
    <article class="agent-card">
      <div class="agent-top">
        <div>
          <div class="strategy-name">${a.asset} · ${a.strategy}</div>
          <div class="agent-id">${a.agent_id}</div>
        </div>
        <span class="status ${a.status}">${a.status}</span>
      </div>
      <div class="agent-score">${num(a.survival_score,0)}<small>/100 Survival</small></div>
      ${tfBadges(a)}
      <div class="agent-metrics">
        <div><span>1H Return</span><strong class="${a.total_return>=0?'pass':'fail'}">${pct(a.total_return)}</strong></div>
        <div><span>1H OOS</span><strong class="${a.oos_return>=0?'pass':'fail'}">${pct(a.oos_return)}</strong></div>
        <div><span>Max DD</span><strong>${pct(a.max_drawdown)}</strong></div>
        <div><span>Profit Factor</span><strong>${num(a.profit_factor)}</strong></div>
        <div><span>Sharpe</span><strong>${num(a.sharpe)}</strong></div>
        <div><span>Trades</span><strong>${a.trades}</strong></div>
        <div><span>Win Rate</span><strong>${pct(a.win_rate)}</strong></div>
        <div><span>Signal</span><strong class="signal ${a.latest_signal}">${a.latest_signal}</strong></div>
        <div><span>TF Confirm</span><strong>${a.timeframe_confirmations ?? 0}/${a.timeframe_total ?? 1}</strong></div>
      </div>
    </article>`;
}

function stressCard(a){
  const rows = [
    ["Baseline",a.stress.baseline_positive],
    ["1H OOS",a.stress.oos_positive],
    ["Costs ×2",a.stress.cost_2x_positive],
    ["Costs ×3",a.stress.cost_3x_positive],
  ];
  return `
    <article class="stress-card">
      <h3>${a.asset} · ${a.strategy} · ${num(a.survival_score,0)}/100</h3>
      ${rows.map(([name,ok])=>`<div class="stress-row"><span>${name}</span><strong class="${ok?'pass':'fail'}">${ok?'PASS':'FAIL'}</strong></div>`).join("")}
      <div class="stress-row"><span>Timeframes</span><strong>${a.timeframe_confirmations ?? 0}/${a.timeframe_total ?? 1}</strong></div>
    </article>`;
}

function replacementCard(r){
  return `
    <article class="replacement-card">
      <strong>${r.agent_id}</strong>
      <p>Parent: ${r.parent}<br>${r.asset} · ${r.strategy}<br>${r.note}</p>
    </article>`;
}

function paperCard(a){
  const pnl = Number(a.equity) / Number(a.initial_equity) - 1;
  const winRate = a.closed_trades ? a.winning_trades / a.closed_trades : 0;
  const position = a.position ? "LONG" : "FLAT";
  return `
    <article class="paper-card">
      <div class="agent-top">
        <div>
          <div class="strategy-name">${a.asset} · ${a.strategy}</div>
          <div class="agent-id">${a.agent_id}</div>
        </div>
        <span class="signal ${position}">${position}</span>
      </div>
      <div class="paper-equity">${money(a.equity)} <small class="${pnl>=0?'pass':'fail'}">${pct(pnl)}</small></div>
      <div class="agent-metrics">
        <div><span>Forward Max DD</span><strong>${pct(a.max_drawdown)}</strong></div>
        <div><span>Closed trades</span><strong>${a.closed_trades}</strong></div>
        <div><span>Trade win rate</span><strong>${pct(winRate)}</strong></div>
        <div><span>Updates</span><strong>${a.updates}</strong></div>
        <div><span>Last event</span><strong>${a.last_event}</strong></div>
        <div><span>Last price</span><strong>${money(a.last_price)}</strong></div>
      </div>
    </article>`;
}

function renderMarket(data){
  $("feedStatus").textContent = "LIVE · CLOSED KRAKEN BARS";
  $("firewallStatus").textContent = data.capital_firewall;
  $("agentCount").textContent = data.summary.agents;
  $("activeCount").textContent = data.summary.active;
  $("probationCount").textContent = data.summary.probation;
  $("eliminatedCount").textContent = data.summary.eliminated;

  if(data.method?.timeframes) $("timeframes").textContent = data.method.timeframes.join(" · ");
  if(data.performance){
    $("parallelFeeds").textContent = data.performance.parallel_market_requests;
    $("engineLatency").textContent = num(data.performance.total_ms,0)+" ms";
  }

  $("markets").innerHTML = data.markets.map(marketCard).join("");
  $("strategyAgents").innerHTML = data.rooms.strategy.length ? data.rooms.strategy.map(agentCard).join("") : empty("لا يوجد Agent اجتاز شروط Active متعددة الأطر الزمنية الآن.");
  $("probationAgents").innerHTML = data.rooms.probation.length ? data.rooms.probation.map(agentCard).join("") : empty("لا يوجد Agents تحت Probation حاليًا.");
  $("graveyard").innerHTML = data.rooms.graveyard.length ? data.rooms.graveyard.map(agentCard).join("") : empty("لا يوجد Agents مقصاة حاليًا.");
  $("redTeam").innerHTML = data.rooms.red_team.length ? data.rooms.red_team.map(stressCard).join("") : empty("لا توجد بيانات Stress.");
  $("replacements").innerHTML = data.rooms.replacement.length ? data.rooms.replacement.map(replacementCard).join("") : empty("لا يوجد Replacement مطلوب الآن.");

  $("source").textContent = data.source;
  $("updated").textContent = new Date(data.generated_at_utc).toLocaleString("en-GB",{timeZone:"UTC"})+" UTC";
  $("oos").textContent = data.method.oos_split;
  $("activationGate").textContent = data.method.activation_rule || data.method.rule;
}

function renderPaper(data){
  if(!data.agents){
    $("paperSummary").innerHTML = '<div class="paper-kpi"><span>Status</span><strong>INITIALIZING</strong></div>';
    $("paperAgents").innerHTML = empty("أول Forward Paper Tick قيد التهيئة.");
    return;
  }

  const agents = Object.values(data.agents).sort((a,b)=>Number(b.equity)-Number(a.equity));
  const base = Number(data.initial_equity_per_agent || 10000);
  const avg = Number(data.summary?.average_equity || base);
  const avgPnl = avg / base - 1;
  const started = data.started_at_utc ? new Date(data.started_at_utc) : null;

  $("paperSummary").innerHTML = `
    <div class="paper-kpi"><span>Started</span><strong>${started ? started.toLocaleDateString("en-GB")+" "+started.toLocaleTimeString("en-GB",{hour:"2-digit",minute:"2-digit"}) : "—"}</strong></div>
    <div class="paper-kpi"><span>Average PnL</span><strong class="${avgPnl>=0?'pass':'fail'}">${pct(avgPnl)}</strong></div>
    <div class="paper-kpi"><span>Closed trades</span><strong>${data.summary?.total_closed_trades ?? 0}</strong></div>
    <div class="paper-kpi"><span>Worst DD</span><strong>${pct(data.summary?.max_observed_drawdown ?? 0)}</strong></div>
  `;

  $("paperAgents").innerHTML = agents.length ? agents.map(paperCard).join("") : empty("لا توجد Agents في سجل الـPaper بعد.");
}

async function loadMarket(){
  $("refreshBtn").disabled = true;
  $("refreshBtn").textContent = "جاري التحديث…";
  $("feedStatus").textContent = "FETCHING…";
  try{
    const res = await fetch("/api/aegis");
    const data = await res.json();
    if(!res.ok || !data.ok) throw new Error(data.error || "API error");
    renderMarket(data);
  }catch(err){
    console.error(err);
    $("feedStatus").textContent = "DATA ERROR";
    $("markets").innerHTML = empty("تعذر جلب بيانات السوق الآن.");
  }finally{
    $("refreshBtn").disabled = false;
    $("refreshBtn").textContent = "تحديث البيانات";
  }
}

async function loadPaper(){
  try{
    const res = await fetch("/api/paper");
    const data = await res.json();
    renderPaper(data);
  }catch(err){
    console.error(err);
    $("paperAgents").innerHTML = empty("تعذر قراءة Forward Paper Ledger الآن.");
  }
}

function refreshAll(){
  loadMarket();
  loadPaper();
}

$("refreshBtn").addEventListener("click",refreshAll);
refreshAll();
setInterval(loadMarket,60000);
setInterval(loadPaper,60000);
