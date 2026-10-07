const $ = (id) => document.getElementById(id);
const money = (v) => new Intl.NumberFormat("en-US",{style:"currency",currency:"USD",maximumFractionDigits:2}).format(Number(v||0));
const pct = (v,d=2) => (Number(v||0)*100).toFixed(d)+"%";
const num = (v,d=2) => Number(v||0).toFixed(d);
const cls = (v) => Number(v||0) >= 0 ? "positive" : "negative";
const when = (ts) => new Date(Number(ts)*1000).toLocaleString("en-GB",{timeZone:"UTC",month:"short",day:"2-digit",hour:"2-digit",minute:"2-digit"})+" UTC";

let current = null;

function marketCard(m){
  return \`
    <article class="market-card">
      <div class="market-top">
        <div><div class="symbol">\${m.symbol}/USD</div><div class="\${m.change_24h>=0?'up':'down'}">\${pct(m.change_24h)}</div></div>
        <div class="price">\${money(m.price)}</div>
      </div>
      <div class="meta">
        <div><span>7D</span><strong>\${pct(m.change_7d)}</strong></div>
        <div><span>VOL</span><strong>\${pct(m.annualized_volatility)}</strong></div>
        <div><span>REGIME</span><strong>\${m.regime}</strong></div>
      </div>
    </article>\`;
}

function agentCard(a){
  const statusClass = a.status.toLowerCase();
  return \`
    <article class="agent-card \${statusClass}">
      <div class="agent-top">
        <div>
          <div class="agent-name">\${a.asset} · \${a.strategy}</div>
          <div class="agent-id">\${a.agent_id}</div>
        </div>
        <span class="status \${a.status}">\${a.status}</span>
      </div>
      <div class="agent-score">\${num(a.survival_score,0)}<small>/100 survival</small></div>
      <div class="agent-metrics">
        <div><span>Paper P&amp;L</span><strong class="\${cls(a.realized_pnl+a.unrealized_pnl)}">\${money(a.realized_pnl+a.unrealized_pnl)}</strong></div>
        <div><span>Trades</span><strong>\${a.trade_count}</strong></div>
        <div><span>Win Rate</span><strong>\${pct(a.win_rate)}</strong></div>
        <div><span>PF</span><strong>\${num(a.profit_factor)}</strong></div>
        <div><span>OOS</span><strong class="\${cls(a.research.oos_return)}">\${pct(a.research.oos_return)}</strong></div>
        <div><span>Signal</span><strong class="signal \${a.latest_signal}">\${a.latest_signal}</strong></div>
      </div>
    </article>\`;
}

function tradeRow(t,i){
  return \`
    <tr data-trade="\${i}">
      <td>\${t.agent_id}</td>
      <td>\${t.asset}</td>
      <td class="\${t.result==='WIN'?'win':'loss'}">\${t.result}</td>
      <td class="\${cls(t.net_pnl)}">\${money(t.net_pnl)}</td>
      <td class="\${cls(t.r_multiple)}">\${num(t.r_multiple)}R</td>
      <td>\${t.exit_reason}</td>
    </tr>\`;
}

function showAutopsy(t){
  $("autopsy").classList.remove("empty");
  $("autopsy").innerHTML = \`
    <h3>\${t.agent_id} · \${t.asset} · \${t.result}</h3>
    <div class="autopsy-grid">
      <div><span>Entry</span><strong>\${money(t.entry)}</strong></div>
      <div><span>Exit</span><strong>\${money(t.exit)}</strong></div>
      <div><span>Stop</span><strong>\${money(t.stop)}</strong></div>
      <div><span>Target</span><strong>\${money(t.target)}</strong></div>
      <div><span>Net P&amp;L</span><strong class="\${cls(t.net_pnl)}">\${money(t.net_pnl)}</strong></div>
      <div><span>R Multiple</span><strong>\${num(t.r_multiple)}R</strong></div>
      <div><span>Fees</span><strong>\${money(t.fees)}</strong></div>
      <div><span>Slippage</span><strong>\${money(t.slippage_cost)}</strong></div>
    </div>
    <p><strong>Why entered:</strong> \${t.signal_reason}<br><strong>Why exited:</strong> \${t.exit_reason}<br><strong>Window:</strong> \${when(t.entry_ts)} → \${when(t.exit_ts)}</p>\`;
}

function ghostCard(g){
  return \`
    <article class="ghost-card">
      <strong>\${g.agent_id}</strong>
      <p>\${g.reason}<br>Signal: \${when(g.signal_ts)} @ \${money(g.signal_price)}</p>
      <div class="ghost-return \${cls(g.forward_12h_return)}">12h forward: \${pct(g.forward_12h_return)}</div>
    </article>\`;
}

function intelCard(a){
  const sec = a.sec || {};
  const finra = a.finra || {};
  const counts = sec.counts || {};
  const latest = finra.latest || {};
  const ratio = latest.short_volume_ratio == null ? "—" : pct(latest.short_volume_ratio);
  const finraDate = latest.date || "—";
  const sourceState = a.sources_available + "/2 sources";
  return `
    <article class="intel-card">
      <div class="intel-top">
        <div><div class="symbol">${a.symbol}</div><div class="agent-id">${sourceState}</div></div>
        <div class="intel-score">${num(a.attention_score,0)}<small>/100 attention</small></div>
      </div>
      <div class="intel-metrics">
        <div><span>Form 4 · 7D</span><strong>${counts.form4_7d ?? "—"}</strong></div>
        <div><span>8-K · 30D</span><strong>${counts["8k_30d"] ?? "—"}</strong></div>
        <div><span>FINRA Short Vol</span><strong>${ratio}</strong></div>
        <div><span>Flow Anomaly</span><strong>${finra.anomaly_score == null ? "—" : num(finra.anomaly_score,0)+"/100"}</strong></div>
        <div><span>FINRA Date</span><strong>${finraDate}</strong></div>
        <div><span>Role</span><strong>CONTEXT ONLY</strong></div>
      </div>
      ${a.errors?.length ? `<p class="intel-error">${a.errors.join(" · ")}</p>` : ""}
    </article>`;
}

function renderIntelligence(data){
  const box = $("intelHQ");
  if(!data?.ok){
    box.innerHTML = '<div class="empty">Intelligence API غير متاح حاليًا.</div>';
    return;
  }
  box.innerHTML = data.assets?.length
    ? data.assets.map(intelCard).join("")
    : '<div class="empty">لا توجد بيانات Intelligence.</div>';
}

async function loadIntelligence(){
  try{
    const res = await fetch("/api/intelligence",{cache:"no-store"});
    const data = await res.json();
    if(!res.ok || !data.ok) throw new Error(data.error || "Intelligence API error");
    renderIntelligence(data);
  }catch(err){
    console.error(err);
    $("intelHQ").innerHTML = '<div class="empty">تعذر جلب SEC / FINRA الآن؛ Agent City الأساسي مستمر بدونها.</div>';
  }
}

function render(data){
  current = data;
  $("feedStatus").textContent = "LIVE · KRAKEN 1H";
  $("firewall").textContent = data.capital_firewall;
  $("mode").textContent = data.mode;
  $("updated").textContent = new Date(data.generated_at_utc).toLocaleTimeString("en-GB",{timeZone:"UTC",hour:"2-digit",minute:"2-digit"});

  const v = data.vault;
  $("equity").textContent = money(v.marked_equity);
  $("netPnl").textContent = money(v.net_pnl); $("netPnl").className = cls(v.net_pnl);
  $("realized").textContent = money(v.realized_pnl); $("realized").className = cls(v.realized_pnl);
  $("unrealized").textContent = money(v.unrealized_pnl); $("unrealized").className = cls(v.unrealized_pnl);
  $("drawdown").textContent = pct(v.max_drawdown);
  $("profitFactor").textContent = num(v.profit_factor);
  $("winRate").textContent = pct(v.win_rate);
  $("costs").textContent = money(v.fees + v.slippage_cost);

  $("markets").innerHTML = data.markets.map(marketCard).join("");

  const r = data.risk;
  $("riskRules").innerHTML = [
    ["Risk / trade",pct(r.risk_per_trade)],
    ["Max notional",pct(r.max_position_notional_pct)],
    ["ATR stop",num(r.atr_stop_multiple)+"×"],
    ["Reward / Risk",num(r.reward_to_risk)+"R"],
    ["Fees / side",num(r.fee_bps_per_side)+" bps"],
    ["Slippage / side",num(r.slippage_bps_per_side)+" bps"],
    ["Agent DD breaker",pct(r.max_agent_drawdown_pct)],
    ["Live execution","OFF"],
  ].map(([a,b])=>\`<div><span>\${a}</span><strong>\${b}</strong></div>\`).join("");
  $("paperNote").textContent = data.paper_execution.description;

  $("agents").innerHTML = data.agents.length ? data.agents.map(agentCard).join("") : '<div class="empty">لا توجد Agents.</div>';

  $("trades").innerHTML = data.trades.length ? data.trades.map(tradeRow).join("") : '<tr><td colspan="6">لا توجد صفقات Paper مغلقة في النافذة الحالية.</td></tr>';
  document.querySelectorAll("[data-trade]").forEach(row=>{
    row.addEventListener("click",()=>showAutopsy(data.trades[Number(row.dataset.trade)]));
  });

  $("ghosts").innerHTML = data.ghost_trades.length ? data.ghost_trades.slice(0,10).map(ghostCard).join("") : '<div class="empty">لا توجد Ghost Trades حاليًا.</div>';

  $("nextStage").innerHTML = \`
    <div><span>Requirement</span><strong>\${data.next_stage.requires}</strong></div>
    <div><span>Promotion Rule</span><strong>\${data.next_stage.promotion_rule}</strong></div>\`;
}

async function load(){
  $("refreshBtn").disabled = true;
  $("refreshBtn").textContent = "جاري التحديث…";
  $("feedStatus").textContent = "FETCHING…";
  try{
    const res = await fetch("/api/city?t="+Date.now(),{cache:"no-store"});
    const data = await res.json();
    if(!res.ok || !data.ok) throw new Error(data.error || "API error");
    render(data);
  }catch(err){
    console.error(err);
    $("feedStatus").textContent = "DATA ERROR";
    $("markets").innerHTML = '<div class="empty">تعذر جلب Agent City API.</div>';
  }finally{
    $("refreshBtn").disabled = false;
    $("refreshBtn").textContent = "تحديث الآن";
  }
}

$("refreshBtn").addEventListener("click",()=>{ load(); loadIntelligence(); });
load();
loadIntelligence();
setInterval(load,60000);
setInterval(loadIntelligence,900000);
