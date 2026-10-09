/* MT5 MetaApi cloud connection UI. No broker login/password ever reaches AEGIS.
 * The browser may submit only the separate owner control key to trigger a
 * read-only snapshot, never an order.
 */
"use strict";
(() => {
  const $ = id => document.getElementById(id);
  const status = $("mt5LinkStatus"), detail = $("mt5LinkLastSync");
  const help = $("mt5PairHelp"), owner = $("mt5OwnerKey");
  const sync = $("mt5CloudSync"), refreshButton = $("mt5CloudRefresh");
  let configured = false, busy = false;
  const setMessage = message => { help.textContent = message; };
  const update = () => {sync.disabled = busy || !configured || owner.value.trim().length < 24;};
  async function refresh(preserveMessage=false) {
    if(busy)return;
    try{
      const response = await fetch("/api/mt5_cloud",{cache:"no-store",headers:{"Accept":"application/json"}});
      const doc = await response.json();
      if(!response.ok || doc.ok !== true)throw new Error("service_unavailable");
      configured = doc.state === "CONNECTED_DEMO";
      if(doc.state === "CONNECTED_DEMO"){
        status.textContent = "متصل · حساب MT5 Demo مؤكد (قراءة فقط)";
        detail.textContent = "اتصال سحابي مؤكد من MetaApi؛ آخر سجل محفوظ يظهر في صفحة الصفقات.";
        if(!preserveMessage)setMessage("لجلب آخر صفقات الذهب إلى Neon، أدخل مفتاح المالك واضغط المزامنة.");
      } else if(doc.state === "SETUP_REQUIRED"){
        status.textContent = "بانتظار إعداد MetaApi في Vercel Preview";
        detail.textContent = "لم تُضبط بيانات AEGIS_METAAPI_TOKEN و AEGIS_METAAPI_ACCOUNT_ID بعد.";
        setMessage("اربط حسابك أولًا في MetaApi، ثم ضع رمز MetaApi ومعرّف الحساب في أسرار Vercel. لا تلصقها هنا.");
      } else if(doc.state === "NOT_VERIFIED"){
        status.textContent = "غير مؤكد · لا توجد موافقة لتداول MT5";
        detail.textContent = doc.reason === "not_verified_demo_account"
          ? "الحساب ليس Demo بحسب MetaApi. تم رفض الاتصال." : "الخدمة السحابية غير متصلة أو بيانات الاعتماد غير صحيحة.";
        setMessage("راجع اتصال الحساب التجريبي في MetaApi ومنطقة حسابك (london أو new-york).");
      } else{
        status.textContent = "إعداد MetaApi غير صالح";
        detail.textContent = "راجع متغيرات Vercel Preview، ولا تحاول استخدام حساب Real.";
        setMessage("لا يمكن مزامنة حساب غير موثّق.");
      }
    } catch(error){
      configured = false;
      status.textContent = "فحص MT5 السحابي غير متاح";
      detail.textContent = "لا نعرض أي صفقات غير موثقة أو بيانات تجريبية.";
      setMessage("تحقق من نشر Vercel واتصال MetaApi؛ لم يتم إرسال أي أمر تداول.");
    }
    update();
  }
  async function syncNow(){
    if(sync.disabled)return;
    busy=true;update();
    setMessage("جاري قراءة معلومات MT5 Demo ومراكزه وسجل صفقات الذهب من MetaApi والتحقق من Neon…");
    try{
      const response=await fetch("/api/mt5_cloud",{
        method:"POST",cache:"no-store",credentials:"same-origin",
        headers:{"Content-Type":"application/json","Authorization":"Bearer "+owner.value.trim()},
        body:JSON.stringify({action:"sync"})
      });
      const data=await response.json();
      owner.value="";
      if(!response.ok || data.ok !== true){
        const reasons={
          owner_control_key_not_configured:"أضف AEGIS_CONTROL_TOKEN إلى Vercel Preview أولًا.",
          unauthorized:"مفتاح المالك غير صحيح.",
          metaapi_not_configured:"حساب MetaApi غير مربوط في Vercel.",
          not_verified_demo_account:"تم رفض الحساب لأنه ليس MT5 Demo موثقًا.",
          demo_ledger_sync_unavailable:"لم نتمكن من حفظ سجل الصفقات في Neon. تحقق من الجداول والصلاحيات.",
          metaapi_read_unavailable:"تعذر قراءة بيانات MetaApi. تحقق من الحساب والمنطقة."
        };
        throw new Error(reasons[data.error]||"فشلت المزامنة بأمان دون إرسال أوامر تداول.");
      }
      setMessage("تمت مزامنة "+Number(data.new_fills||0)+" صفقة جديدة من MT5 Demo و"+Number(data.open_positions||0)+" مراكز مفتوحة في Neon. لا توجد أوامر وسيط.");
    } catch(error){
      setMessage(error.message || "فشل الاتصال السحابي. لم تُرسل صفقات.");
    }finally{
      busy=false;update();await refresh(true);
    }
  }
  owner.addEventListener("input",update);
  sync.addEventListener("click",syncNow);
  refreshButton.addEventListener("click",refresh);
  refresh();
  window.setInterval(()=>{if(!document.hidden&&!busy)refresh()},60000);
})();
