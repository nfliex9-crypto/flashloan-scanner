const $ = (id) => document.getElementById(id);

const money = (v) => new Intl.NumberFormat("en-US",{style:"currency",currency:"USD",maximumFractionDigits:2}).format(Number(v));
const pct = (v,d=2) => (Number(v)*100).toFixed(d)+"%";
const num = (v,d=2) => Number(v).toFixed(d);

const tickerState = {
  ws: null,
  connected: false,
  reconnectTimer: null,
  pingTimer: null,
  quotes: {},
};

function feedLabel(){
  if(tickerState.connected) return "LIVE · KRAKEN WS + CLOSED BARS";
  return "LIVE · CLOSED KRAKEN BARS";
}

function empty(text){ return '<div class="empty">'+text+'</div>'; }

function marketCard(m){
  const cls = m.change_24h >= 0 ? "up" : "down";
  const closed = m.last_candle_utc ? new Date(m.last_candle_utc).toLocaleTimeString("en-GB",{hour:"2-digit",minute:"2-digit"}) : "—";
  const micro = m.microstructure || {};
  const imbalance = Number(micro.book_imbalance || 0);
  return `
    <article class="market-card" data-market-symbol="${m.symbol}">
      <div class="market-top">
        <div>
          <span class="symbol">${m.symbol}/USD</span>
          <div class="delta ${cls}">${pct(m.change_24h)}</div>
        </div>
        <div class="live-price-wrap">
          <span class="live-caption">LIVE MID</span>
          <div class="price live-price">${money(m.price)}</div>
        </div>
      </div>
      <div class="micro-row">
        <span>Bid <strong class="live-bid">${micro.best_bid ? money(micro.best_bid) : "—"}</strong></span>
        <span>Ask <strong class="live-ask">${micro.best_ask ? money(micro.best_ask) : "—"}</strong></span>
        <span>Spread <strong class="live-spread">${micro.spread_bps != null ? num(micro.spread_bps,2)+" bps" : "—"}</strong></span>
      </div>
      <div class="depth-grid">
        <div><span>$10K Buy Slip</span><strong>${micro.buy_10k_slippage_bps != null ? num(micro.buy_10k_slippage_bps,2)+" bps" : "—"}</strong></div>
        <div><span>$10K Sell Slip</span><strong>${micro.sell_10k_slippage_bps != null ? num(micro.sell_10k_slippage_bps,2)+" bps" : "—"}</strong></div>
        <div><span>Book Imbalance</span><strong class="${imbalance>=0?'pass':'fail'}">${pct(imbalance)}</strong></div>
        <div><span>Taker Fee</span><strong>${micro.taker_fee_bps != null ? num(micro.taker_fee_bps,0)+" bps" : "—"}</strong></div>
      </div>
      <div class="market-meta">
        <div><span>7D Return</span><strong>${pct(m.change_7d)}</strong></div>
        <div><span>Annualized Vol</span><strong>${pct(m.annualized_volatility)}</strong></div>
        <div><span>Regime</span><strong class="regime">${m.regime}</strong></div>
        <div><span>Closed bar</span><strong>${closed}</strong></div>
      </div>
    </article>`;
}


function applyTicker(symbol, quote){
  const card = document.querySelector(`[data-market-symbol="${symbol}"]`);
  if(!card || !quote) return;

  const bid = Number(quote.bid);
  const ask = Number(quote.ask);
  const mid = bid > 0 && ask > 0 ? (bid + ask) / 2 : Number(quote.last || 0);
  const spreadBps = bid > 0 && ask > 0 && mid > 0 ? ((ask - bid) / mid) * 10000 : null;

  const priceEl = card.querySelector(".live-price");
  const bidEl = card.querySelector(".live-bid");
  const askEl = card.querySelector(".live-ask");
  const spreadEl = card.querySelector(".live-spread");

  if(priceEl && mid > 0) priceEl.textContent = money(mid);
  if(bidEl && bid > 0) bidEl.textContent = money(bid);
  if(askEl && ask > 0) askEl.textContent = money(ask);
  if(spreadEl) spreadEl.textContent = spreadBps == null ? "—" : num(spreadBps,2)+" bps";
}

function hydrateTickerCards(){
  for(const [symbol,quote] of Object.entries(tickerState.quotes)){
    applyTicker(symbol,quote);
  }
}

function stopTickerHeartbeat(){
  if(tickerState.pingTimer){
    clearInterval(tickerState.pingTimer);
    tickerState.pingTimer = null;
  }
}

function scheduleTickerReconnect(){
  if(tickerState.reconnectTimer) return;
  tickerState.reconnectTimer = setTimeout(()=>{
    tickerState.reconnectTimer = null;
    startTickerStream();
  },5000);
}

function startTickerStream(){
  if(
    tickerState.ws &&
    (tickerState.ws.readyState === WebSocket.OPEN ||
     tickerState.ws.readyState === WebSocket.CONNECTING)
  ) return;

  const ws = new WebSocket("wss://ws.kraken.com/v2");
  tickerState.ws = ws;

  ws.addEventListener("open",()=>{
    tickerState.connected = true;
    $("feedStatus").textContent = feedLabel();

    ws.send(JSON.stringify({
      method:"subscribe",
      params:{
        channel:"ticker",
        symbol:["BTC/USD","ETH/USD"],
        event_trigger:"bbo",
        snapshot:true
      }
    }));

    stopTickerHeartbeat();
    tickerState.pingTimer = setInterval(()=>{
      if(ws.readyState === WebSocket.OPEN){
        ws.send(JSON.stringify({method:"ping"}));
      }
    },25000);
  });

  ws.addEventListener("message",(event)=>{
    try{
      const message = JSON.parse(event.data);
      if(message.channel !== "ticker" || !Array.isArray(message.data)) return;

      for(const item of message.data){
        const raw = item.symbol || "";
        const symbol = raw.split("/")[0];
        if(!["BTC","ETH"].includes(symbol)) continue;

        tickerState.quotes[symbol] = {
          bid:item.bid,
          ask:item.ask,
          last:item.last,
          timestamp:item.timestamp
        };
        applyTicker(symbol,tickerState.quotes[symbol]);
      }
    }catch(err){
      console.debug("Ticker message ignored",err);
    }
  });

  ws.addEventListener("close",()=>{
    tickerState.connected = false;
    stopTickerHeartbeat();
    $("feedStatus").textContent = feedLabel();
    scheduleTickerReconnect();
  });

  ws.addEventListener("error",()=>{
    tickerState.connected = false;
    $("feedStatus").textContent = feedLabel();
    try{ ws.close(); }catch{}
  });
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
  const lastFill = a.last_fill || {};
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
        <div><span>Real fees</span><strong>${money(a.total_fees_usd || 0)}</strong></div>
        <div><span>Slippage cost</span><strong>${money(a.total_slippage_usd || 0)}</strong></div>
        <div><span>Last fill slip</span><strong>${lastFill.slippage_bps != null ? num(lastFill.slippage_bps,2)+" bps" : "—"}</strong></div>
        <div><span>Last event</span><strong>${a.last_event}</strong></div>
        <div><span>Updates</span><strong>${a.updates}</strong></div>
        <div><span>Missed-bar gaps</span><strong>${a.missed_bar_events || 0}</strong></div>
      </div>
    </article>`;
}


function evolutionCard(row){
  const genome = row.genome || {};
  return `
    <article class="evolution-card">
      <div class="agent-top">
        <div>
          <div class="strategy-name">${row.family}</div>
          <div class="agent-id">${genome.genome_id || "—"}</div>
        </div>
        <span class="status ${row.status || "ACTIVE"}">${row.status || "ACTIVE"}</span>
      </div>
      <div class="agent-score">${num(row.score,0)}<small>/100 Robustness</small></div>
      <div class="agent-metrics">
        <div><span>Generation</span><strong>${genome.generation ?? 0}</strong></div>
        <div><span>TF Confirm</span><strong>${row.confirmations ?? 0}/3</strong></div>
        <div><span>Worst DD</span><strong>${pct(row.worst_drawdown || 0)}</strong></div>
      </div>
      <div class="genome-params">${Object.entries(genome.params || {}).map(([k,v])=>`<span>${k}=<strong>${v}</strong></span>`).join("")}</div>
    </article>`;
}

function evolutionEventCard(event){
  const judge = (event.role_trace || []).find(x=>x.role==="JUDGE");
  const promoted = judge?.event === "PROMOTE";
  const best = event.best_challenger || {};
  return `
    <div class="evolution-event ${promoted?'promoted':''}">
      <div>
        <strong>${event.family}</strong>
        <span>cycle ${event.cycle} · strikes ${event.strikes ?? 0}</span>
      </div>
      <div class="event-decision ${promoted?'pass':'neutral'}">${judge?.event || "EVALUATED"}</div>
      <small>best challenger: ${best.genome?.genome_id || "—"} · score ${num(best.evaluation?.score || 0,1)}</small>
      <small>${judge?.reason || ""}</small>
    </div>`;
}

function renderEvolution(data){
  if(!data.cycle){
    $("evolutionSummary").innerHTML = '<div class="paper-kpi"><span>Status</span><strong>INITIALIZING</strong></div>';
    $("hallOfFame").innerHTML = empty("أول Evolution Cycle قيد التشغيل.");
    $("evolutionEvents").innerHTML = empty("لا توجد قرارات بعد.");
    return;
  }

  const summary = data.summary || {};
  $("evolutionSummary").innerHTML = `
    <div class="paper-kpi"><span>Cycle</span><strong>${data.cycle}</strong></div>
    <div class="paper-kpi"><span>Challengers tested</span><strong>${summary.challengers_tested ?? 0}</strong></div>
    <div class="paper-kpi"><span>Promotions</span><strong class="pass">${summary.promotions_this_cycle ?? 0}</strong></div>
    <div class="paper-kpi"><span>Probation / Eliminated</span><strong>${summary.probation ?? 0} / ${summary.eliminated ?? 0}</strong></div>
  `;

  $("hallOfFame").innerHTML = (data.hall_of_fame || []).length
    ? data.hall_of_fame.map(evolutionCard).join("")
    : empty("Hall of Fame لم يتكوّن بعد.");

  const events = (data.events || []).slice(-8).reverse();
  $("evolutionEvents").innerHTML = events.length
    ? events.map(evolutionEventCard).join("")
    : empty("لا توجد قرارات تطوير بعد.");
}

function renderMarket(data){
  $("feedStatus").textContent = feedLabel();
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
  hydrateTickerCards();
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
    <div class="paper-kpi"><span>Total fees</span><strong>${money(data.summary?.total_fees_usd ?? 0)}</strong></div>
    <div class="paper-kpi"><span>Total slippage</span><strong>${money(data.summary?.total_slippage_usd ?? 0)}</strong></div>
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


async function loadEvolution(){
  try{
    const res = await fetch("/api/evolution");
    const data = await res.json();
    renderEvolution(data);
  }catch(err){
    console.error(err);
    $("evolutionSummary").innerHTML = '<div class="paper-kpi"><span>Status</span><strong class="fail">ERROR</strong></div>';
    $("hallOfFame").innerHTML = empty("تعذر قراءة Evolution Ledger.");
    $("evolutionEvents").innerHTML = empty("تعذر قراءة سجل التطوير.");
  }
}


const controlState = {
  token: "",
  riskTimer: null,
};

function riskParams(){
  return {
    capital: Number($("capitalInput")?.value || 10000),
    risk_pct: Number($("riskInput")?.value || 1),
    stop_pct: Number($("stopInput")?.value || 2),
    max_position_pct: Number($("maxPositionInput")?.value || 25),
    notional: Number($("notionalInput")?.value || 0),
    fee_bps: Number($("feeInput")?.value || 80),
  };
}

function saveRiskParams(){
  try{
    localStorage.setItem("aegis-risk-controls", JSON.stringify(riskParams()));
  }catch{}
}

function restoreRiskParams(){
  try{
    const saved = JSON.parse(localStorage.getItem("aegis-risk-controls") || "{}");
    const map = {
      capital:"capitalInput",
      risk_pct:"riskInput",
      stop_pct:"stopInput",
      max_position_pct:"maxPositionInput",
      notional:"notionalInput",
      fee_bps:"feeInput",
    };
    for(const [key,id] of Object.entries(map)){
      if(saved[key] != null && $(id)) $(id).value = saved[key];
    }
  }catch{}
}

function executionCard(a){
  const buy = a.buy || {};
  return `
    <article class="execution-card">
      <div class="agent-top">
        <strong>${a.symbol}/USD</strong>
        <span class="status ${a.fully_fillable ? "ACTIVE" : "PROBATION"}">${a.fully_fillable ? "FILLABLE" : "PARTIAL"}</span>
      </div>
      <div class="execution-notional">${money(a.notional_usd)}</div>
      <div class="agent-metrics">
        <div><span>Base qty / Lot</span><strong>${num(a.base_quantity,8)}</strong></div>
        <div><span>Spread</span><strong>${num(a.spread_bps,2)} bps</strong></div>
        <div><span>Buy VWAP</span><strong>${money(buy.vwap || 0)}</strong></div>
        <div><span>Buy Slippage</span><strong>${num(buy.slippage_bps || 0,2)} bps</strong></div>
        <div><span>Buy Fee</span><strong>${money(buy.fee_quote || 0)}</strong></div>
        <div><span>Levels Used</span><strong>${buy.levels_used ?? 0}</strong></div>
        <div><span>Roundtrip Drag</span><strong class="fail">${num(a.roundtrip_drag_bps,2)} bps</strong></div>
        <div><span>Roundtrip PnL</span><strong class="${a.roundtrip_pnl_usd >= 0 ? "pass":"fail"}">${money(a.roundtrip_pnl_usd)}</strong></div>
      </div>
    </article>`;
}

function renderExecution(data){
  const z = data.sizing || {};
  $("riskSummary").innerHTML = `
    <div class="paper-kpi"><span>Risk budget</span><strong>${money(z.risk_budget_usd || 0)}</strong></div>
    <div class="paper-kpi"><span>Risk-sized notional</span><strong>${money(z.risk_sized_notional_usd || 0)}</strong></div>
    <div class="paper-kpi"><span>Max position</span><strong>${money(z.max_position_usd || 0)}</strong></div>
    <div class="paper-kpi"><span>Effective Lot / Notional</span><strong>${money(z.effective_notional_usd || 0)}</strong></div>
  `;
  $("executionCards").innerHTML = Object.values(data.assets || {}).map(executionCard).join("");
}

async function loadExecution(){
  if(!$("riskForm")) return;
  saveRiskParams();
  $("simulateBtn").disabled = true;
  $("simulateBtn").textContent = "جاري الحساب…";
  try{
    const p = riskParams();
    const q = new URLSearchParams();
    for(const [k,v] of Object.entries(p)) q.set(k,String(v));
    const res = await fetch("/api/execution?"+q.toString(),{cache:"no-store"});
    const data = await res.json();
    if(!res.ok || !data.ok) throw new Error(data.error || "execution api");
    renderExecution(data);
  }catch(err){
    console.error(err);
    $("riskSummary").innerHTML = empty("تعذر حساب التنفيذ من Order Book الآن.");
    $("executionCards").innerHTML = "";
  }finally{
    $("simulateBtn").disabled = false;
    $("simulateBtn").textContent = "احسب التنفيذ Live";
  }
}

function scheduleExecution(){
  clearTimeout(controlState.riskTimer);
  controlState.riskTimer = setTimeout(loadExecution,450);
}

function testRunCard(run){
  const running = run.status !== "completed";
  const ok = run.conclusion === "success";
  const state = running ? "RUNNING" : (ok ? "PASS" : (run.conclusion || "UNKNOWN").toUpperCase());
  const cls = running ? "warn" : (ok ? "pass" : "fail");
  return `
    <article class="test-card">
      <div class="agent-top">
        <strong>${run.name}</strong>
        <span class="${cls}">${state}</span>
      </div>
      <div class="agent-id">${run.sha || "—"}</div>
      <div class="test-meta">
        <span>${run.title || ""}</span>
        <span>${run.updated_at ? new Date(run.updated_at).toLocaleString("en-GB") : "—"}</span>
      </div>
      ${run.html_url ? `<a href="${run.html_url}" target="_blank" rel="noreferrer">فتح نتيجة الاختبار</a>` : ""}
    </article>`;
}

function renderTests(data){
  const failing = data.failing || 0;
  const running = data.running || 0;
  $("testsBadge").textContent = failing ? "FAILURES" : (running ? "RUNNING" : "ALL GREEN");
  $("testsBadge").className = "room-badge "+(failing ? "danger" : (running ? "warn" : "good"));
  $("testSummary").innerHTML = `
    <div class="paper-kpi"><span>Passing</span><strong class="pass">${data.passing || 0}</strong></div>
    <div class="paper-kpi"><span>Running</span><strong>${running}</strong></div>
    <div class="paper-kpi"><span>Failing</span><strong class="${failing ? "fail":"pass"}">${failing}</strong></div>
  `;
  $("testRuns").innerHTML = (data.runs || []).length ? data.runs.map(testRunCard).join("") : empty("لا توجد نتائج اختبارات متاحة.");
}

async function loadTests(){
  try{
    const res = await fetch("/api/tests");
    const data = await res.json();
    if(!res.ok || !data.ok) throw new Error(data.error || "tests api");
    renderTests(data);
  }catch(err){
    console.error(err);
    $("testsBadge").textContent = "ERROR";
    $("testsBadge").className = "room-badge danger";
    $("testRuns").innerHTML = empty("تعذر قراءة حالة الاختبارات.");
  }
}

function brainCard(a){
  const cls = a.action === "PAPER_ELIGIBLE" ? "ACTIVE" : a.action === "QUARANTINE" ? "ELIMINATED" : "PROBATION";
  return `
    <article class="brain-card">
      <div class="agent-top">
        <div>
          <strong>${a.family}</strong>
          <div class="agent-id">${a.agent_id}</div>
        </div>
        <span class="status ${cls}">${a.action}</span>
      </div>
      <div class="brain-trust">${num(a.trust_score,0)}<small>/100 Trust</small></div>
      <div class="agent-metrics">
        <div><span>Research</span><strong>${num(a.research_score,0)}</strong></div>
        <div><span>Paper PnL</span><strong class="${a.paper_return >= 0 ? "pass":"fail"}">${pct(a.paper_return)}</strong></div>
        <div><span>Paper DD</span><strong>${pct(a.paper_drawdown)}</strong></div>
        <div><span>Closed trades</span><strong>${a.closed_trades}</strong></div>
        <div><span>TF Confirm</span><strong>${a.timeframe_confirmations}/3</strong></div>
        <div><span>Risk cap</span><strong>${num(a.max_risk_multiplier*100,0)}% of base</strong></div>
      </div>
      <div class="brain-reasons">${(a.reasons || []).map(r=>`<span>${r}</span>`).join("") || "<span>waiting for more evidence</span>"}</div>
    </article>`;
}

function renderBrain(data){
  const x=data.summary || {};
  $("brainSummary").innerHTML = `
    <div class="paper-kpi"><span>Paper eligible</span><strong class="pass">${x.paper_eligible || 0}</strong></div>
    <div class="paper-kpi"><span>Shadow only</span><strong>${x.shadow_only || 0}</strong></div>
    <div class="paper-kpi"><span>Probation</span><strong>${x.probation || 0}</strong></div>
    <div class="paper-kpi"><span>Quarantine</span><strong class="${x.quarantine ? "fail":"pass"}">${x.quarantine || 0}</strong></div>
  `;
  $("brainAgents").innerHTML = (data.agents || []).length ? data.agents.map(brainCard).join("") : empty("العقل ينتظر Evidence كافي.");
}

async function loadBrain(){
  try{
    const res = await fetch("/api/brain");
    const data = await res.json();
    if(!res.ok || !data.ok) throw new Error(data.error || "brain api");
    renderBrain(data);
  }catch(err){
    console.error(err);
    $("brainAgents").innerHTML = empty("تعذر تغذية Evidence Brain الآن.");
  }
}

function brokerAccountView(data){
  if(!data.configured){
    $("brokerBadge").textContent = "NEEDS PAPER KEYS";
    $("brokerBadge").className = "room-badge warn";
    $("brokerStatus").innerHTML = `
      <div class="broker-message">
        الموصل جاهز لكن مفاتيح Alpaca Paper غير موجودة على السيرفر بعد.
        بمجرد إضافتها سيظهر Equity وCash والمراكز والأوامر هنا.
      </div>`;
    $("paperBrokerOrder").classList.add("hidden");
    return;
  }

  if(data.locked || !data.connected){
    $("brokerBadge").textContent = "CONFIGURED · LOCKED";
    $("brokerBadge").className = "room-badge warn";
    $("brokerStatus").innerHTML = '<div class="broker-message">الحساب مهيأ. أدخل Control Token لعرضه والتحكم بحساب الـPaper.</div>';
    $("paperBrokerOrder").classList.add("hidden");
    return;
  }

  $("brokerBadge").textContent = "ALPACA PAPER · CONNECTED";
  $("brokerBadge").className = "room-badge good";
  const a=data.account || {};
  const positions=data.positions || [];
  const orders=data.orders || [];
  $("brokerStatus").innerHTML = `
    <div class="broker-kpis">
      <div class="paper-kpi"><span>Equity</span><strong>${money(a.equity || 0)}</strong></div>
      <div class="paper-kpi"><span>Cash</span><strong>${money(a.cash || 0)}</strong></div>
      <div class="paper-kpi"><span>Buying power</span><strong>${money(a.buying_power || 0)}</strong></div>
      <div class="paper-kpi"><span>Max order</span><strong>${money(data.max_order_usd || 0)}</strong></div>
    </div>
    <div class="broker-split">
      <div>
        <h3>Positions</h3>
        ${positions.length ? positions.map(p=>`<div class="broker-line"><span>${p.symbol} · qty ${num(p.qty,6)}</span><strong class="${p.unrealized_pl>=0?'pass':'fail'}">${money(p.unrealized_pl)}</strong></div>`).join("") : '<div class="broker-line"><span>No positions</span></div>'}
      </div>
      <div>
        <h3>Recent orders</h3>
        ${orders.slice(0,6).map(o=>`<div class="broker-line"><span>${o.side?.toUpperCase()} ${o.symbol}</span><strong>${o.status}</strong></div>`).join("") || '<div class="broker-line"><span>No orders</span></div>'}
      </div>
    </div>`;
  $("paperBrokerOrder").classList.remove("hidden");
}

async function loadBroker(){
  try{
    const headers = {};
    if(controlState.token) headers["X-Aegis-Control-Token"] = controlState.token;
    const res = await fetch("/api/broker",{headers,cache:"no-store"});
    const data = await res.json();
    brokerAccountView(data);
  }catch(err){
    console.error(err);
    $("brokerBadge").textContent = "BROKER ERROR";
    $("brokerBadge").className = "room-badge danger";
    $("brokerStatus").innerHTML = empty("تعذر الاتصال بموصل الـPaper.");
  }
}

async function unlockBroker(){
  controlState.token = ($("controlTokenInput").value || "").trim();
  await loadBroker();
}

async function sendPaperOrder(){
  if(!controlState.token){
    $("brokerStatus").insertAdjacentHTML("afterbegin",'<div class="error-box">أدخل Control Token أولًا.</div>');
    return;
  }
  const btn=$("brokerOrderBtn");
  btn.disabled=true;
  btn.textContent="إرسال…";
  try{
    const body={
      action:"place_market_order",
      symbol:$("brokerSymbol").value,
      side:$("brokerSide").value,
      notional_usd:Number($("brokerNotional").value || 0),
    };
    const res=await fetch("/api/broker",{
      method:"POST",
      headers:{
        "Content-Type":"application/json",
        "X-Aegis-Control-Token":controlState.token,
      },
      body:JSON.stringify(body),
    });
    const data=await res.json();
    if(!res.ok || !data.ok) throw new Error(data.error || "paper order failed");
    await loadBroker();
  }catch(err){
    console.error(err);
    $("brokerStatus").insertAdjacentHTML("afterbegin",`<div class="error-box">${String(err.message || err)}</div>`);
  }finally{
    btn.disabled=false;
    btn.textContent="إرسال Paper Order";
  }
}


function refreshAll(){
  loadMarket();
  loadPaper();
  loadEvolution();
  loadExecution();
  loadTests();
  loadBrain();
  loadBroker();
}

$("refreshBtn").addEventListener("click",refreshAll);

restoreRiskParams();
$("riskForm")?.addEventListener("submit",(event)=>{event.preventDefault();loadExecution();});
for(const id of ["capitalInput","riskInput","stopInput","maxPositionInput","notionalInput","feeInput"]){
  $(id)?.addEventListener("input",scheduleExecution);
}
$("brokerUnlockBtn")?.addEventListener("click",unlockBroker);
$("brokerOrderBtn")?.addEventListener("click",sendPaperOrder);

startTickerStream();
refreshAll();
setInterval(loadMarket,60000);
setInterval(loadPaper,60000);
setInterval(loadEvolution,300000);
setInterval(loadTests,60000);
setInterval(loadBrain,60000);
setInterval(loadBroker,60000);
