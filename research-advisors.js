/* External research reviewers are OWNER-ONLY and CANNOT EXECUTE ORDERS.
 * Grok sees a bounded sanitized source-health summary, never account secrets.
 */
"use strict";
(() => {
  const $ = id => document.getElementById(id);
  if (!$("externalResearchPanel")) return;
  const key = $("advisorOwnerKey");
  const run = $("advisorGrokReview");
  const output = $("advisorResult");
  const status = $("advisorStatus");
  const grok = $("advisorGrok");
  let configured = false, busy = false;
  const update = () => {
    run.disabled = busy || !configured || key.value.trim().length < 24;
    $("advisorRefresh").disabled = busy;
  };
  async function check() {
    if (busy) return;
    try {
      const response = await fetch("/api/stage3?research_advisors=1",{
        cache:"no-store",headers:{"Accept":"application/json"}});
      const data = await response.json();
      if(!response.ok || data.ok !== true)throw Error("provider_status_unavailable");
      configured = data.grok?.state === "OWNER_ENABLED";
      grok.textContent = configured
        ? "API مهيّأ · مراجعة يدوية فقط" : "غير مهيّأ · لا توجد طلبات xAI";
      $("advisorJev").textContent = data.jev?.state === "SEPARATE_RAILWAY_SERVICE"
        ? "خدمة Railway مستقلة · دون ربط أوامر" : "غير مؤكد";
      if(!configured){
        status.textContent = "أضف XAI_API_KEY إلى بيئة Preview في Vercel لتمكين المراجعة. Grok ليس جزءًا من فتح صفقات Paper.";
      }
    }catch(error){
      configured=false;
      grok.textContent="تعذر التحقق من جاهزية xAI";
      $("advisorJev").textContent="غير مؤكد من AEGIS";
      status.textContent="تعذّر قراءة جاهزية المراجعين. لم يتم تشغيل أي نموذج أو صفقة.";
    }
    update();
  }
  async function critique() {
    if(busy || !configured || run.disabled)return;
    busy=true;update();
    output.hidden=true;
    output.textContent="";
    status.textContent="جاري جلب الأدلة الحقيقية من Neon ثم طلب مراجعة Grok لمرة واحدة…";
    try{
      const response=await fetch("/api/stage3?grok_review=1",{
        method:"POST",cache:"no-store",credentials:"same-origin",
        headers:{"Authorization":"Bearer "+key.value.trim(),
                 "Content-Type":"application/json"},
        body:JSON.stringify({action:"review"})
      });
      // Never keep the owner key after using it for a single review.
      key.value="";
      const data=await response.json();
      if(!response.ok||data.ok!==true){
        const errors={
          owner_control_key_not_configured:"مفتاح المالك غير معدّ في Vercel Preview.",
          unauthorized:"مفتاح المالك غير صحيح.",
          grok_not_configured:"مفتاح Grok غير موجود في Vercel Preview.",
          neon_source_not_verified:"لا يوجد اتصال Neon موثق؛ تم منع طلب Grok المدفوع.",
          no_fresh_kraken_data:"لا توجد بيانات Kraken حديثة موثقة؛ لم يتم استهلاك Grok.",
          grok_provider_unavailable:"خدمة xAI غير متاحة حاليًا.",
        };
        throw Error(errors[data.error]||"تعذر تشغيل المراجعة. لم تُنفذ أي صفقة.");
      }
      output.hidden=false;
      // Only textContent: the external LLM is NEVER allowed to inject markup.
      output.textContent=String(data.text||"لا توجد مراجعة").slice(0,2400);
      status.textContent="مراجعة "+String(data.model||"Grok")+" اكتملت. تحليل AI غير مثبت؛ لا يغيّر قرارات Paper ولا يضع أوامر.";
    }catch(error){
      status.textContent=error.message||"فشلت مراجعة Grok دون أي تأثير على التداول.";
    }finally{
      busy=false;update();
    }
  }
  key.addEventListener("input",update);
  run.addEventListener("click",critique);
  $("advisorRefresh").addEventListener("click",check);
  check();
})();
