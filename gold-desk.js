/* AEGIS verified Gold Desk: indicative source XAU/USD only.
 * Never claim a Pepperstone broker connection without OAuth and execution receipts.
 */
"use strict";
(() => {
  const $ = id => document.getElementById(id);
  if (!$("goldSpotPrice")) return;
  let busy=false;
  const price=$("goldSpotPrice"),when=$("goldSpotTime"),broker=$("demoStatus");
  async function refresh(){
    if(busy)return;
    busy=true;
    try{
      const response=await fetch("/api/stage3?gold_desk=1",{
        cache:"no-store",headers:{"Accept":"application/json"}});
      if(!response.ok)throw new Error("gold_data_unavailable");
      const data=await response.json();
      if(data.ok!==true||data.mode!=="SOURCE_BACKED_GOLD_MARKET_INFORMATION")
        throw new Error("not_verified_gold_desk");
      const m=data.market||{};
      const valid=m.fresh===true&&m.state==="CURRENT"&&
        m.source==="gold-api.com"&&m.unit==="USD_PER_TROY_OUNCE"&&
        Number.isFinite(Number(m.price))&&Number(m.price)>0;
      const weekend=m.state==="MARKET_CLOSED_WEEKEND";
      const stale=(m.state==="STALE_SOURCE_QUOTE"||weekend)&&
        Number.isFinite(Number(m.last_known_price))&&Number(m.last_known_price)>0;
      const display=valid?m.price:stale?m.last_known_price:null;
      price.textContent=display==null?"—":
        new Intl.NumberFormat("en-US",{style:"currency",currency:"USD",
          minimumFractionDigits:2,maximumFractionDigits:2}).format(display);
      price.dataset.state=valid?"CURRENT":stale?"STALE":"UNVERIFIED";
      when.textContent=(valid||stale)&&m.provider_updated_at?
        (weekend?"سوق الذهب مغلق (عطلة نهاية الأسبوع) · سعر مرجعي فقط: ":
         stale?"آخر سعر معروف (قديم؛ ليس سعرًا مباشرًا): ":"آخر تحديث المصدر: ")+
        new Date(m.provider_updated_at).toLocaleString("ar-BE",{timeZone:"UTC"})+
        " UTC · استرشادي":
        "سعر الذهب غير متاح حاليًا؛ ما رح نعرض رقمًا تخمينيًا.";
      const verified=data.broker?.verified===true && data.broker?.state==="CONNECTED_DEMO";
      broker.textContent=verified?"حساب Pepperstone Demo مرتبط للقراءة فقط":
        "Pepperstone Demo غير مربوط بـAEGIS";
      $("goldDemoPositions").textContent=verified &&
        Number.isInteger(data.broker.positions) ? String(data.broker.positions):"—";
      $("goldDemoTrades").textContent=verified &&
        Number.isInteger(data.broker.fills) ? String(data.broker.fills):"—";
      $("goldIntegrationNote").textContent=verified?
        "مراكز Demo مؤكدة من الوسيط (قراءة فقط).": "لرؤية صفقات Pepperstone افتح Trading Panel في TradingView. AEGIS يحتاج تفويض cTrader مستقلًا للقراءة.";
    }catch(error){
      price.textContent="—";
      price.dataset.state="UNVERIFIED";
      when.textContent="تعذر التحقق من سعر الذهب الخارجي.";
      broker.textContent="حالة Pepperstone Demo غير مؤكدة";
      $("goldDemoPositions").textContent="—";
      $("goldDemoTrades").textContent="—";
      $("goldIntegrationNote").textContent="لا توجد أسعار أو مراكز وسيط اصطناعية.";
    }finally{
      busy=false;
    }
  }
  refresh();
  window.setInterval(()=>{if(!document.hidden)refresh()},45000);
})();
