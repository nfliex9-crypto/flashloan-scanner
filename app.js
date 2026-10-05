const $ = (id) => document.getElementById(id);

const state = {
  interval: 20,
  remaining: 20,
  timer: null,
  loading: false,
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
          <td>${money(r.gas_est_usdc)}</td>
          <td class="${pnlClass}">${money(r.net_pnl_usdc)}</td>
          <td>${status}</td>
        </tr>
      `;
    })
    .join("");
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

    $("block").textContent = num(data.block, 0);
    $("spread").textContent = num(data.spread_pct, 4) + "%";
    $("gas").textContent = money(data.gas_est_usdc);
    const best = data.routes?.[0]?.net_pnl_usdc ?? 0;
    $("bestNet").textContent = money(best);
    $("bestNet").className = best > 0 ? "good" : best < 0 ? "bad" : "neutral";

    renderPrices(data.prices);
    renderRoutes(data.routes);

    $("updatedAt").textContent =
      "آخر تحديث " + new Date().toLocaleTimeString("ar-BE");
    setStatus("ok", "متصل بـ Arbitrum");
  } catch (err) {
    console.error(err);
    setStatus("bad", "فشل الاتصال");
    $("routes").innerHTML =
      '<tr><td colspan="7"><div class="error-box">تعذر جلب البيانات الآن. جرّب تحديث الصفحة أو استخدم RPC أقوى.</div></td></tr>';
  } finally {
    state.loading = false;
    $("refreshBtn").disabled = false;
    state.remaining = state.interval;
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
$("tradeSize").addEventListener("change", refresh);

refresh();
startTimer();
