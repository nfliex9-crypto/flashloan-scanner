const $ = (id) => document.getElementById(id);
const STORAGE_KEY = "flashloan-scanner-history-v2";

const state = {
  interval: 20,
  remaining: 20,
  timer: null,
  loading: false,
  optimizing: false,
  preflighting: false,
  radarLoading: false,
  deepLoading: false,
  minProfit: 1,
  history: loadHistory(),
};

const money = (value, digits = 4) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: digits,
  }).format(value);

const num = (value, digits = 4) =>
  new Intl.NumberFormat("en-US", {
    maximumFractionDigits: digits,
  }).format(value);

function loadHistory() {
  try {
    const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
    return Array.isArray(parsed) ? parsed.slice(-80) : [];
  } catch {
    return [];
  }
}

function saveHistory() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state.history.slice(-80)));
}

function setStatus(kind, text) {
  $("statusDot").className = "dot " + kind;
  $("statusText").textContent = text;
}

function renderPrices(prices) {
  $("prices").innerHTML = prices
    .map(
      (p) => `
        <article class="price-card">
          <div class="dex">${p.dex}</div>
          <div class="value">${money(p.weth_usdc, 4)}</div>
          <div class="fee">Pool fee: ${p.fee}</div>
        </article>
      `
    )
    .join("");
}

function renderRoutes(routes) {
  $("routes").innerHTML = routes
    .map((r) => {
      const pnlClass = r.net_pnl_usdc > 0 ? "good" : r.net_pnl_usdc < 0 ? "bad" : "neutral";
      const status = r.opportunity
        ? '<span class="good">OPPORTUNITY</span>'
        : '<span class="neutral">NO TRADE</span>';

      return `
        <tr>
          <td class="route-name">${r.name}</td>
          <td>${money(r.end_usdc)}</td>
          <td class="${r.gross_pnl_usdc >= 0 ? "good" : "bad"}">${money(r.gross_pnl_usdc)}</td>
          <td>${num(r.impact_est_pct, 4)}%</td>
          <td>${money(r.borrow_fee_est_usdc)}</td>
          <td>${money(r.gas_est_usdc)}</td>
          <td class="${pnlClass}">${money(r.net_pnl_usdc)}</td>
          <td>${status}</td>
        </tr>
      `;
    })
    .join("");
}

function recordSnapshot(data) {
  const best = data.routes?.[0];
  if (!best) return;

  const last = state.history[state.history.length - 1];
  if (last && last.block === data.block && last.size === data.trade_size_usdc) return;

  state.history.push({
    ts: Date.now(),
    block: data.block,
    size: data.trade_size_usdc,
    spread: data.spread_pct,
    bestNet: best.net_pnl_usdc,
    route: best.name,
    opportunity: best.opportunity,
  });

  state.history = state.history.slice(-80);
  saveHistory();
  renderHistory();
}

function renderHistory() {
  $("scanCount").textContent = state.history.length;
  const opportunities = state.history.filter((x) => x.opportunity).length;
  $("opportunityCount").textContent = opportunities;

  if (state.history.length) {
    const bestEver = Math.max(...state.history.map((x) => x.bestNet));
    $("bestEver").textContent = money(bestEver);
    $("bestEver").className = bestEver > 0 ? "good" : bestEver < 0 ? "bad" : "neutral";
  } else {
    $("bestEver").textContent = "—";
    $("bestEver").className = "";
  }

  const rows = state.history.slice(-8).reverse();
  $("historyRows").innerHTML = rows.length
    ? rows
        .map(
          (x) => `
            <tr>
              <td>${new Date(x.ts).toLocaleTimeString("ar-BE", { hour: "2-digit", minute: "2-digit" })}</td>
              <td>${money(x.size, 0)}</td>
              <td>${num(x.spread, 4)}%</td>
              <td class="${x.bestNet > 0 ? "good" : "bad"}">${money(x.bestNet)}</td>
            </tr>
          `
        )
        .join("")
    : '<tr><td colspan="4" class="loading-row">لا يوجد سجل بعد</td></tr>';

  drawHistoryChart();
}

function drawHistoryChart() {
  const canvas = $("historyChart");
  const parentWidth = canvas.parentElement?.clientWidth || 600;
  const dpr = window.devicePixelRatio || 1;
  const cssHeight = 220;

  canvas.style.width = "100%";
  canvas.style.height = cssHeight + "px";
  canvas.width = Math.max(320, parentWidth) * dpr;
  canvas.height = cssHeight * dpr;

  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);

  const width = canvas.width / dpr;
  const height = cssHeight;
  const pad = 26;
  const data = state.history.slice(-40);

  ctx.clearRect(0, 0, width, height);
  ctx.strokeStyle = "rgba(147,197,253,.16)";
  ctx.lineWidth = 1;

  for (let i = 0; i < 4; i += 1) {
    const y = pad + ((height - pad * 2) * i) / 3;
    ctx.beginPath();
    ctx.moveTo(pad, y);
    ctx.lineTo(width - pad, y);
    ctx.stroke();
  }

  if (data.length < 2) {
    ctx.fillStyle = "#8fa3ba";
    ctx.font = "13px system-ui";
    ctx.textAlign = "center";
    ctx.fillText("سيظهر الرسم بعد أكثر من فحص", width / 2, height / 2);
    return;
  }

  const values = data.map((x) => x.bestNet);
  let min = Math.min(...values, 0);
  let max = Math.max(...values, 0);
  if (min === max) {
    min -= 1;
    max += 1;
  }

  const xFor = (i) => pad + (i / (data.length - 1)) * (width - pad * 2);
  const yFor = (v) => pad + ((max - v) / (max - min)) * (height - pad * 2);

  const zeroY = yFor(0);
  ctx.strokeStyle = "rgba(245,196,81,.38)";
  ctx.beginPath();
  ctx.moveTo(pad, zeroY);
  ctx.lineTo(width - pad, zeroY);
  ctx.stroke();

  ctx.strokeStyle = "#4de7ff";
  ctx.lineWidth = 2;
  ctx.beginPath();
  data.forEach((point, i) => {
    const x = xFor(i);
    const y = yFor(point.bestNet);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();

  const last = data[data.length - 1];
  ctx.fillStyle = last.bestNet >= 0 ? "#45e6a1" : "#ff6b7d";
  ctx.beginPath();
  ctx.arc(xFor(data.length - 1), yFor(last.bestNet), 4, 0, Math.PI * 2);
  ctx.fill();
}

async function refresh() {
  if (state.loading) return;

  const size = Number($("tradeSize").value || 1000);
  if (!Number.isFinite(size) || size <= 0) {
    setStatus("bad", "حجم غير صالح");
    return;
  }

  state.loading = true;
  $("refreshBtn").disabled = true;
  setStatus("loading", "جاري تحديث البيانات...");

  try {
    const res = await fetch(`/api/scan?size=${encodeURIComponent(size)}&t=${Date.now()}`, {
      cache: "no-store",
    });
    const data = await res.json();

    if (!res.ok || !data.ok) {
      throw new Error(data.error || "API error");
    }

    state.minProfit = data.min_net_profit_usdc ?? 1;
    $("block").textContent = num(data.block, 0);
    $("spread").textContent = num(data.spread_pct, 4) + "%";
    $("gas").textContent = money(data.gas_est_usdc);
    $("aaveFee").textContent = num(data.flashloan_fee_pct, 3) + "%";

    const best = data.routes?.[0]?.net_pnl_usdc ?? 0;
    $("bestNet").textContent = money(best);
    $("bestNet").className = best > 0 ? "good" : best < 0 ? "bad" : "neutral";

    renderPrices(data.prices);
    renderRoutes(data.routes);
    recordSnapshot(data);

    $("updatedAt").textContent =
      "آخر تحديث " + new Date().toLocaleTimeString("ar-BE");
    setStatus("ok", "متصل بـ Arbitrum");
  } catch (err) {
    console.error(err);
    setStatus("bad", "فشل الاتصال");
    $("routes").innerHTML =
      '<tr><td colspan="8"><div class="error-box">تعذر جلب البيانات الآن. جرّب التحديث مرة ثانية.</div></td></tr>';
  } finally {
    state.loading = false;
    $("refreshBtn").disabled = false;
    state.remaining = state.interval;
  }
}

function renderOptimizer(data) {
  $("optimizerEmpty").classList.add("hidden");
  $("optimizerResult").classList.remove("hidden");

  const best = data.best;
  $("bestSize").textContent = money(best.size_usdc, 0);
  $("bestRoute").textContent = best.name;
  $("optimizedNet").textContent = money(best.net_pnl_usdc);
  $("optimizedNet").className =
    best.net_pnl_usdc > 0 ? "good" : best.net_pnl_usdc < 0 ? "bad" : "neutral";

  $("optimizerCandidates").innerHTML = data.candidates
    .slice(0, 8)
    .map(
      (r) => `
        <tr>
          <td>${money(r.size_usdc, 0)}</td>
          <td class="route-name">${r.name}</td>
          <td class="${r.gross_pnl_usdc >= 0 ? "good" : "bad"}">${money(r.gross_pnl_usdc)}</td>
          <td>${money(r.borrow_fee_est_usdc)}</td>
          <td class="${r.net_pnl_usdc > 0 ? "good" : "bad"}">${money(r.net_pnl_usdc)}</td>
        </tr>
      `
    )
    .join("");
}

async function optimizeSize() {
  if (state.optimizing) return;
  state.optimizing = true;
  $("optimizeBtn").disabled = true;
  $("optimizeBtn").textContent = "جاري التحليل...";

  try {
    const res = await fetch(`/api/scan?mode=optimize&t=${Date.now()}`, {
      cache: "no-store",
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "Optimizer error");

    renderOptimizer(data);

    if (data.best?.net_pnl_usdc >= state.minProfit) {
      $("tradeSize").value = data.best.size_usdc;
    }
  } catch (err) {
    console.error(err);
    $("optimizerEmpty").classList.remove("hidden");
    $("optimizerEmpty").textContent = "تعذر تشغيل محلل الأحجام الآن. جرّب مرة ثانية.";
  } finally {
    state.optimizing = false;
    $("optimizeBtn").disabled = false;
    $("optimizeBtn").textContent = "أفضل حجم الآن";
  }
}



function renderRadar(data) {
  $("radarAssets").textContent = data.assets_scanned ?? "—";
  $("radarRoutes").textContent = data.routes_quoted ?? "—";
  $("radarPositive").textContent = data.positive_count ?? 0;
  $("radarProfitable").textContent = data.profitable_count ?? 0;

  $("radarEmpty").classList.add("hidden");
  $("radarResult").classList.remove("hidden");

  const rows = (data.results || []).slice(0, 12);
  $("radarRows").innerHTML = rows.length
    ? rows
        .map((r) => {
          const status = r.opportunity
            ? '<span class="good">OPPORTUNITY</span>'
            : r.net_pnl_usdc > 0
              ? '<span class="warm">POSITIVE</span>'
              : '<span class="neutral">NO TRADE</span>';

          return `
            <tr>
              <td><strong>${r.token}</strong></td>
              <td class="route-name">${r.route}</td>
              <td class="${r.gross_pnl_usdc >= 0 ? "good" : "bad"}">${num(r.gross_edge_pct, 4)}%</td>
              <td>${money(r.flash_fee_usdc)}</td>
              <td>${money(r.gas_est_usdc)}</td>
              <td class="${r.net_pnl_usdc > 0 ? "good" : "bad"}">${money(r.net_pnl_usdc)}</td>
              <td>${status}</td>
            </tr>
          `;
        })
        .join("")
    : '<tr><td colspan="7" class="loading-row">لم يتم العثور على مسارات قابلة للتسعير.</td></tr>';
}

async function runRadar() {
  if (state.radarLoading) return;

  const size = Number($("tradeSize").value || 1000);
  if (!Number.isFinite(size) || size <= 0) return;

  state.radarLoading = true;
  $("radarBtn").disabled = true;
  $("radarBtn").textContent = "جاري فحص عدة أسواق...";
  $("radarEmpty").classList.remove("hidden");
  $("radarEmpty").textContent = "يتم الآن تسعير الأصول والمسارات مباشرة من Arbitrum...";

  try {
    const res = await fetch(
      `/api/opportunities?size=${encodeURIComponent(size)}&t=${Date.now()}`,
      { cache: "no-store" }
    );
    const data = await res.json();

    if (!res.ok || !data.ok) throw new Error(data.error || "Radar error");
    renderRadar(data);
  } catch (err) {
    console.error(err);
    $("radarEmpty").classList.remove("hidden");
    $("radarResult").classList.add("hidden");
    $("radarEmpty").textContent = "تعذر إكمال البحث الموسع الآن. جرّب مرة ثانية.";
  } finally {
    state.radarLoading = false;
    $("radarBtn").disabled = false;
    $("radarBtn").textContent = "بحث موسع الآن";
  }
}


function renderDeepScan(data) {
  const best = data.best;
  $("deepEmpty").classList.add("hidden");
  $("deepResult").classList.remove("hidden");

  if (!best) {
    $("deepToken").textContent = "—";
    $("deepSize").textContent = "—";
    $("deepRoute").textContent = "—";
    $("deepNet").textContent = "—";
    $("deepRows").innerHTML =
      '<tr><td colspan="6" class="loading-row">لم يتم العثور على مسار قابل للتحسين.</td></tr>';
    return;
  }

  $("deepToken").textContent = best.token;
  $("deepSize").textContent = money(best.size_usdc, 0);
  $("deepRoute").textContent = best.route;
  $("deepNet").textContent = money(best.net_pnl_usdc);
  $("deepNet").className = best.net_pnl_usdc > 0 ? "good" : "bad";

  $("deepRows").innerHTML = (data.optimized_results || [])
    .slice(0, 8)
    .map(
      (r) => `
        <tr>
          <td><strong>${r.token}</strong></td>
          <td>${money(r.size_usdc, 0)}</td>
          <td class="route-name">${r.route}</td>
          <td class="${r.gross_pnl_usdc >= 0 ? "good" : "bad"}">${money(r.gross_pnl_usdc)}</td>
          <td>${money(r.flash_fee_usdc)}</td>
          <td class="${r.net_pnl_usdc > 0 ? "good" : "bad"}">${money(r.net_pnl_usdc)}</td>
        </tr>
      `
    )
    .join("");
}

async function runDeepScan() {
  if (state.deepLoading) return;

  const size = Number($("tradeSize").value || 1000);
  if (!Number.isFinite(size) || size <= 0) return;

  state.deepLoading = true;
  $("deepBtn").disabled = true;
  $("deepBtn").textContent = "Deep Scan جاري...";
  $("deepEmpty").classList.remove("hidden");
  $("deepEmpty").textContent =
    "نفحص أفضل المسارات على عدة أحجام. هذا الفحص أبطأ لأنه يستخدم Quotes حقيقية من البلوكشين.";

  try {
    const res = await fetch(
      `/api/deep?size=${encodeURIComponent(size)}&t=${Date.now()}`,
      { cache: "no-store" }
    );
    const data = await res.json();

    if (!res.ok || !data.ok) throw new Error(data.error || "Deep scan error");
    renderDeepScan(data);
  } catch (err) {
    console.error(err);
    $("deepResult").classList.add("hidden");
    $("deepEmpty").classList.remove("hidden");
    $("deepEmpty").textContent =
      "تعذر إكمال Deep Scan الآن. قد يكون الـRPC محدودًا؛ جرّب مرة ثانية.";
  } finally {
    state.deepLoading = false;
    $("deepBtn").disabled = false;
    $("deepBtn").textContent = "Deep Scan للأحجام";
  }
}

function renderPreflight(data) {
  $("preflightEmpty").classList.add("hidden");
  $("preflightResult").classList.remove("hidden");

  const execute = data.status === "WOULD_EXECUTE";
  $("preflightBadge").textContent = execute ? "WOULD EXECUTE" : "WOULD REVERT";
  $("preflightBadge").className = "pill " + (execute ? "success-pill" : "danger-pill");
  $("preflightStatus").textContent = data.status.replace("_", " ");
  $("preflightStatus").className = execute ? "good" : "bad";
  $("preflightRoute").textContent = data.route?.name || "—";
  $("preflightNet").textContent = money(data.route?.net_pnl_usdc || 0);
  $("preflightNet").className =
    (data.route?.net_pnl_usdc || 0) > 0 ? "good" : "bad";
  $("preflightShortfall").textContent = money(data.profit_shortfall_usdc || 0);
  $("preflightReason").textContent = data.reason || "";

  $("preflightChecks").innerHTML = (data.checks || [])
    .map(
      (check) => `
        <div class="check-card ${check.ok ? "check-ok" : "check-fail"}">
          <div class="check-icon">${check.ok ? "✓" : "×"}</div>
          <div>
            <strong>${check.name}</strong>
            <span>${check.detail}</span>
          </div>
        </div>
      `
    )
    .join("");
}

async function runPreflight() {
  if (state.preflighting) return;

  const size = Number($("tradeSize").value || 1000);
  if (!Number.isFinite(size) || size <= 0) {
    setStatus("bad", "حجم غير صالح");
    return;
  }

  state.preflighting = true;
  $("preflightBtn").disabled = true;
  $("preflightBtn").textContent = "جاري المحاكاة...";

  try {
    const res = await fetch(
      `/api/scan?mode=preflight&size=${encodeURIComponent(size)}&t=${Date.now()}`,
      { cache: "no-store" }
    );
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "Preflight error");
    renderPreflight(data);
  } catch (err) {
    console.error(err);
    $("preflightEmpty").classList.remove("hidden");
    $("preflightResult").classList.add("hidden");
    $("preflightBadge").textContent = "فشل الفحص";
    $("preflightBadge").className = "pill danger-pill";
    $("preflightEmpty").textContent = "تعذر تشغيل محاكاة التنفيذ الآن. جرّب مرة ثانية.";
  } finally {
    state.preflighting = false;
    $("preflightBtn").disabled = false;
    $("preflightBtn").textContent = "محاكاة التنفيذ";
  }
}

function startTimer() {
  clearInterval(state.timer);
  state.timer = setInterval(() => {
    state.remaining -= 1;
    if (state.remaining <= 0) {
      refresh();
      state.remaining = state.interval;
    }
    $("countdown").textContent = state.remaining;
  }, 1000);
}

$("refreshBtn").addEventListener("click", refresh);
$("optimizeBtn").addEventListener("click", optimizeSize);
$("preflightBtn").addEventListener("click", runPreflight);
$("radarBtn").addEventListener("click", runRadar);
$("deepBtn").addEventListener("click", runDeepScan);
$("tradeSize").addEventListener("change", refresh);
$("clearHistoryBtn").addEventListener("click", () => {
  state.history = [];
  saveHistory();
  renderHistory();
});
window.addEventListener("resize", drawHistoryChart);

renderHistory();
refresh();
setTimeout(runRadar, 2500);
startTimer();
