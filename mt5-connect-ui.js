/* Owner-gated MT5 DEMO onboarding; browser never receives broker credentials.
 * A pairing key authorizes READ-ONLY bridge snapshots, not trade orders.
 */
"use strict";
(() => {
  const el = id => document.getElementById(id);
  const state = el("mt5LinkStatus"), last = el("mt5LinkLastSync");
  const hint = el("mt5PairHelp"), owner = el("mt5OwnerKey");
  const create = el("mt5PairCreate"), revoke = el("mt5PairRevoke");
  const panel = el("mt5PairSecret"), tokenLabel = el("mt5PairToken");
  let pairingCode = "", schemaReady = false, busy = false, connected = false;

  const setHint = message => { hint.textContent = message; };
  const time = value => value ? new Date(value).toLocaleString("ar-BE") : "—";
  async function refresh() {
    try {
      const response = await fetch("/api/mt5_link",{cache:"no-store",headers:{"Accept":"application/json"}});
      const data = await response.json();
      if (!response.ok || data.ok !== true) throw Error(data.error || "connection_status_unavailable");
      schemaReady = data.state !== "SETUP_REQUIRED";
      connected = data.state === "CONNECTED_DEMO" || data.state === "STALE_DEMO";
      const labels = {
        CONNECTED_DEMO:"متصل بحساب MT5 Demo · قراءة فقط",
        STALE_DEMO:"المزامنة متأخرة · افحص موصل Windows",
        AWAITING_CONNECTOR:"بانتظار تشغيل موصل Windows",
        UNLINKED:"لا يوجد حساب MT5 Demo مربوط",
        SETUP_REQUIRED:"إعداد قاعدة البيانات مطلوب"
      };
      state.textContent = labels[data.state] || "حالة اتصال غير معروفة";
      last.textContent = data.last_synced
        ? "آخر مزامنة: " + time(data.last_synced) + (data.market ? " · " + data.market : "")
        : "لا توجد صفقات مزامنة معتمدة بعد";
      if (!schemaReady) setHint("يجب تطبيق sql/007_demo_accounts.sql و sql/012_mt5_pairings.sql على قاعدة Neon المخصصة أولًا. لا يمكن إتمام الربط حتى يتم ذلك.");
      else if(!pairingCode) setHint("لإنشاء رمز الربط، أدخل مفتاح AEGIS_CONTROL_TOKEN الخاص بالموقع (وليس بيانات MT5).");
    } catch(error) {
      schemaReady = false;
      connected = false;
      state.textContent = "تعذر التحقق من خدمة MT5";
      last.textContent = "لا يمكن الادعاء بأن الحساب متصل دون قراءة موثقة";
      setHint("خدمة ربط MT5 غير متاحة حاليًا. تحقق من نشر Vercel واتصال Neon.");
    }
    updateActions();
  }
  function updateActions() {
    const authorized = owner.value.trim().length >= 24;
    create.disabled = busy || !schemaReady || !authorized;
    revoke.disabled = busy || !schemaReady || !authorized || !connected;
  }
  async function request(action) {
    if (busy || !schemaReady || owner.value.trim().length < 24) return;
    if(action === "revoke" && !window.confirm("فصل جميع موصلات MT5 Demo لهذا المشروع؟ سيُرفض أي تحديث لاحق حتى يتم ربط جديد."))return;
    busy = true; updateActions();
    panel.hidden = true; tokenLabel.textContent = ""; pairingCode = "";
    setHint("جاري التحقق من طلب المالك…");
    try {
      const res = await fetch("/api/mt5_link",{
        method:"POST",cache:"no-store",credentials:"same-origin",
        headers:{"Content-Type":"application/json","Authorization":"Bearer "+owner.value.trim()},
        body:JSON.stringify({action})
      });
      const data = await res.json();
      if(!res.ok || data.ok !== true)throw Error(data.error || "operation_failed");
      if(action==="create"){
        pairingCode = String(data.pairing_token || "");
        if(!/^[a-zA-Z0-9_-]{40,60}$/.test(pairingCode))throw Error("invalid_server_pairing_code");
        tokenLabel.textContent = pairingCode;
        panel.hidden = false;
        setHint("الرمز صالح 15 دقيقة قبل أول اقتران. افتح MT5 Demo على Windows ثم شغّل موصل الربط.");
      } else {
        setHint("تم إلغاء صلاحية الربط. لا يُسمح بأي مزامنة جديدة بهذا الرمز.");
      }
      owner.value = "";
    } catch(error){
      const codes = {
        owner_control_key_not_configured:"مفتاح AEGIS_CONTROL_TOKEN غير مُعدّ في Vercel Preview.",
        unauthorized:"مفتاح المالك غير صحيح.",
        mt5_pairing_schema_missing:"جدول الربط في Neon غير جاهز بعد.",
        mt5_pairing_service_unavailable:"خدمة MT5 أو قاعدة Neon غير متاحة حاليًا."
      };
      setHint(codes[error.message] || "تعذر إتمام عملية الربط. لم تُرسل أي أوامر MT5.");
    } finally {
      busy = false;
      updateActions();
      // Retain the one-time code on screen while its value is still needed.
      await refresh();
    }
  }
  owner.addEventListener("input",updateActions);
  create.addEventListener("click",()=>request("create"));
  revoke.addEventListener("click",()=>request("revoke"));
  el("mt5PairCopy").addEventListener("click", async () => {
    if(!pairingCode)return;
    try {
      await navigator.clipboard.writeText(pairingCode);
      setHint("تم نسخ الرمز. الصقه فقط داخل موصل MT5 على Windows.");
    } catch(error) {
      setHint("النسخ التلقائي غير متاح في هذا المتصفح؛ ظلّل الرمز وانسخه يدويًا.");
    }
  });
  refresh();
  window.setInterval(()=>{if(!document.hidden&&!busy)refresh()},15000);
})();
