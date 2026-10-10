/* AEGIS source-health canaries — Vibe-Trading-inspired and read-only.
 * This panel displays ONLY Neon receipts and timestamps returned by ops_health.
 */
"use strict";
(() => {
  const $ = id => document.getElementById(id);
  if (!$("opsHealthPanel")) return;
  const labels = {
    CONNECTED:"Neon متصل · قراءة ناجحة",
    UNAVAILABLE:"قاعدة البيانات غير متاحة",
    READY:"الجدول جاهز",
    SCHEMA_MISSING:"جداول ناقصة",
    NO_EVIDENCE:"لا يوجد تنفيذ موثق",
    CURRENT:"آخر تشغيل موثّق حديث",
    STALE:"آخر تشغيل قديم",
    READ_FAILED:"تعذر قراءة السجل",
    UNVERIFIED:"لم يتم التحقق",
    ALL_VERIFIED:"7 / 7 مصادر موثقة",
    PARTIAL_VERIFIED:"مصادر متصلة جزئيًا",
    NO_FRESH_EVIDENCE:"لا توجد مصادر حديثة",
  };
  const label = state => labels[state] || "حالة غير معروفة";
  let fetching = false;
  function value(id, state, extra = "") {
    const node=$(id);
    node.textContent=label(state)+(extra ? " · "+extra : "");
    node.dataset.state=state||"UNKNOWN";
  }
  async function refresh(){
    if(fetching) return;
    fetching=true;
    $("healthRefresh").disabled=true;
    try{
      const response=await fetch("/api/stage3?diagnostics=1", {
        cache:"no-store", headers:{"Accept":"application/json"}});
      if(!response.ok) throw Error("diagnostics_endpoint_unavailable");
      const data=await response.json();
      if(data.ok!==true || data.mode!=="SOURCE_BACKED_READ_ONLY_DIAGNOSTICS")
        throw Error("invalid_health_evidence");
      value("healthDatabase",data.database?.state);
      value("healthMonitor",data.market_monitor?.state);
      value("healthForward",data.hourly_forward?.state);
      const stream=data.kraken_paper||{},healthy=stream.healthy_intervals_minutes||[];
      value("healthKraken",stream.state,healthy.length+" / "+
        (stream.expected_intervals_minutes||[]).length+" فواصل");
      value("healthGold",data.mt5_demo?.state);
      const parts=[];
      const missing=data.forward_paper_schema?.missing_tables||[];
      if(missing.length)parts.push("جداول Paper غير جاهزة: "+missing.join("، "));
      if(stream.missing_tables?.length)parts.push("جداول Kraken ناقصة: "+stream.missing_tables.join("، "));
      if(stream.missing_intervals_minutes?.length)parts.push("فواصل غير مؤكدة: "+
        stream.missing_intervals_minutes.join("m، ")+"m");
      if(data.database?.state!=="CONNECTED")parts.push("Neon غير متاح؛ حالة التداول غير مؤكدة.");
      if(data.market_monitor?.state!=="CURRENT")
        parts.push("جدولة 15 دقيقة ليست مثبتة كتشغيل حديث.");
      if(data.hourly_forward?.state!=="CURRENT")
        parts.push("آخر دورة Forward Paper ليست حديثة أو غير موجودة.");
      if(data.mt5_demo?.state!=="CURRENT")
        parts.push("MT5 Demo غير متصل بسجل حديث؛ Bitcoin Paper مستقل.");
      $("healthExplanation").textContent=parts.length ? parts.join(" · ") :
        "Neon وPaper وKraken وMT5 لها سجلات تشغيل حديثة. هذا لا يعني أن استراتيجية رابحة أو أن أوامر Demo مفعلة.";
      $("healthCheckedAt").textContent=data.checked_at
        ? "فُحصت السجلات: "+new Date(data.checked_at).toLocaleString("ar-BE")
        : "التحقق من اتصال قاعدة البيانات فشل؛ لا توجد بيانات مزيفة.";
    }catch(error){
      ["healthDatabase","healthMonitor","healthForward","healthKraken","healthGold"]
        .forEach(id=>value(id,"UNVERIFIED"));
      $("healthExplanation").textContent=
        "Endpoint التشخيص غير متاح. لا نعرض نتائج تقديرية ولا ندّعي اتصال المحركات.";
      $("healthCheckedAt").textContent="فشل جلب الأدلة";
    }finally{
      fetching=false;
      $("healthRefresh").disabled=false;
    }
  }
  $("healthRefresh").addEventListener("click",refresh);
  refresh();
  window.setInterval(()=>{if(!document.hidden)refresh()},60_000);
})();
