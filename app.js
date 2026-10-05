const $ = (id) => document.getElementById(id);

const money = (v) => new Intl.NumberFormat("en-US",{style:"currency",currency:"USD",maximumFractionDigits:2}).format(v);
const pct = (v,d=2) => (v*100).toFixed(d)+"%";
const num = (v,d=2) => Number(v).toFixed(d);

function empty(text){ return '<div class="empty">'+text+'</div>'; }

function marketCard(m){
  const cls = m.change_24h >= 0 ? "up" : "down";
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
        <div><span>Bars</span><strong>${m.bars}</strong></div>
      </div>
    </article>`;
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
      <div class="agent-metrics">
        <div><span>Total Return</span><strong class="${a.total_return>=0?'pass':'fail'}">${pct(a.total_return)}</strong></div>
        <div><span>OOS Return</span><strong class="${a.oos_return>=0?'pass':'fail'}">${pct(a.oos_return)}</strong></div>
        <div><span>Max DD</span><strong>${pct(a.max_drawdown)}</strong></div>
        <div><span>Profit Factor</span><strong>${num(a.profit_factor)}</strong></div>
        <div><span>Sharpe</span><strong>${num(a.sharpe)}</strong></div>
        <div><span>Trades</span><strong>${a.trades}</strong></div>
        <div><span>Win Rate</span><strong>${pct(a.win_rate)}</strong></div>
        <div><span>Signal</span><strong class="signal ${a.latest_signal}">${a.latest_signal}</strong></div>
        <div><span>Stress</span><strong>${a.stress_passes}/4</strong></div>
      </div>
    </article>`;
}

function stressCard(a){
  const rows = [
    ["Baseline",a.stress.baseline_positive],
    ["Out-of-Sample",a.stress.oos_positive],
    ["Costs ×2",a.stress.cost_2x_positive],
    ["Costs ×3",a.stress.cost_3x_positive],
  ];
  return `
    <article class="stress-card">
      <h3>${a.asset} · ${a.strategy} · ${num(a.survival_score,0)}/100</h3>
      ${rows.map(([name,ok])=>`<div class="stress-row"><span>${name}</span><strong class="${ok?'pass':'fail'}">${ok?'PASS':'FAIL'}</strong></div>`).join("")}
    </article>`;
}

function replacementCard(r){
  return `
    <article class="replacement-card">
      <strong>${r.agent_id}</strong>
      <p>Parent: ${r.parent}<br>${r.asset} · ${r.strategy}<br>${r.note}</p>
    </article>`;
}

function render(data){
  $("feedStatus").textContent = "LIVE · KRAKEN 1H";
  $("firewallStatus").textContent = data.capital_firewall;
  $("agentCount").textContent = data.summary.agents;
  $("activeCount").textContent = data.summary.active;
  $("probationCount").textContent = data.summary.probation;
  $("eliminatedCount").textContent = data.summary.eliminated;

  $("markets").innerHTML = data.markets.map(marketCard).join("");
  $("strategyAgents").innerHTML = data.rooms.strategy.length ? data.rooms.strategy.map(agentCard).join("") : empty("لا يوجد Agent اجتاز شروط Active في هذه النافذة.");
  $("probationAgents").innerHTML = data.rooms.probation.length ? data.rooms.probation.map(agentCard).join("") : empty("لا يوجد Agents تحت Probation حاليًا.");
  $("graveyard").innerHTML = data.rooms.graveyard.length ? data.rooms.graveyard.map(agentCard).join("") : empty("لا يوجد Agents مقصاة حاليًا.");
  $("redTeam").innerHTML = data.rooms.red_team.length ? data.rooms.red_team.map(stressCard).join("") : empty("لا توجد بيانات Stress.");
  $("replacements").innerHTML = data.rooms.replacement.length ? data.rooms.replacement.map(replacementCard).join("") : empty("لا يوجد Replacement مطلوب الآن.");

  $("source").textContent = data.source;
  $("updated").textContent = new Date(data.generated_at_utc).toLocaleString("en-GB",{timeZone:"UTC"})+" UTC";
  $("oos").textContent = data.method.oos_split;
  $("costModel").textContent = data.method.cost_model;
}

async function load(){
  $("refreshBtn").disabled = true;
  $("refreshBtn").textContent = "جاري التحديث…";
  $("feedStatus").textContent = "FETCHING…";
  try{
    const res = await fetch("/api/aegis?t="+Date.now(),{cache:"no-store"});
    const data = await res.json();
    if(!res.ok || !data.ok) throw new Error(data.error || "API error");
    render(data);
  }catch(err){
    console.error(err);
    $("feedStatus").textContent = "DATA ERROR";
    $("markets").innerHTML = empty("تعذر جلب بيانات السوق الآن.");
  }finally{
    $("refreshBtn").disabled = false;
    $("refreshBtn").textContent = "تحديث البيانات";
  }
}

$("refreshBtn").addEventListener("click",load);
load();
setInterval(load,60000);
