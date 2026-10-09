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
      const response = await fetch("/api/stage3?mt5_cloud=1",{cache:"no-store",headers:{"Accept":"application/json"}});
      const doc = await response.json();
      if(!response.ok || doc.ok !== true)throw new Error("service_unavailable");
      configured = doc.state === "READY_FOR_VERIFICATION";
      if(doc.state === "READY_FOR_VERIFICATION"){
        status.textContent = "MetaApi مهيّأ · بانتظار التحقق من Demo وInvestor";
        detail.textContent = "تجهيز API لا يثبت الاتصال؛ اضغط المزامنة بترخيص المالك لفحص حساب MT5 التجريبي.";
        // Display only broker evidence actually persisted in Neon, never
        // interpret a configured API token as a verified MT5 connection.
        try{
          const ledgerRes=await fetch("/api/stage3",{cache:"no-store"});
          if(ledgerRes.ok){
            const ledger=await ledgerRes.json();
            const mt5=(ledger.demo_brokers?.connected_accounts||[])
              .find(a=>a.provider==="MT5_DEMO");
            if(mt5?.last_synced){
              const delta=Date.now()-Date.parse(mt5.last_synced);
              const date=new Date(mt5.last_synced).toLocaleString("ar-BE");
              if(Number.isFinite(delta) && delta>=0 && delta<300000){
                status.textContent="سجل MT5 Demo متزامن · قراءة فقط";
              } else {
                status.textContent="آخر سجل MT5 Demo قديم · يلزم مزامنة";
              }
              detail.textContent="آخر سجل وسيط محفوظ: "+date;
            }
          }
        }catch(error){ /* Fail closed: no synthetic broker status. */ }
        if(!preserveMessage)setMessage("أدخل مفتاح المالك ثم اضغط المزامنة للتحقق من Investor Mode وحساب Demo قبل حفظ أي صفقة.");
      } else if(doc.state === "SETUP_REQUIRED"){
        status.textContent = "بانتظار إعداد MetaApi في Vercel Preview";
        detail.textContent = "لم تُضبط بيانات AEGIS_METAAPI_TOKEN و AEGIS_METAAPI_ACCOUNT_ID بعد.";
        if(!preserveMessage)setMessage("اربط حسابك أولًا في MetaApi، ثم ضع رمز MetaApi ومعرّف الحساب في أسرار Vercel. لا تلصقها هنا.");
      } else{
        status.textContent = "إعداد MetaApi غير صالح";
        detail.textContent = "راجع متغيرات Vercel Preview، ولا تحاول استخدام حساب Real.";
        if(!preserveMessage)setMessage("لا يمكن مزامنة حساب غير موثّق.");
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
      const response=await fetch("/api/stage3?mt5_cloud=1",{
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
          investor_mode_not_verified:"تم رفض الربط: يجب الاتصال في MetaApi بكلمة مرور Investor للقراءة فقط، لا كلمة مرور التداول.",
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
