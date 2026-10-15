"use strict";
// Local calculation only: NO API, NO data feed, NO orders.
const form = document.getElementById("riskForm");
const usd = n => Number.isFinite(n) ? new Intl.NumberFormat("en-US", {style:"currency",currency:"USD",maximumFractionDigits:2}).format(n) : "—";
const num = id => Number(document.getElementById(id).value);
const write = (id,v) => { document.getElementById(id).textContent=v; };
function compute(e) {
  if(e) e.preventDefault();
  const ids=["initial","balance","equity","eod","peak","loss","daily","daystart","budget"];
  if(ids.some(id=>!document.getElementById(id).value.trim() || !Number.isFinite(num(id)))) {
    write("riskMessage","الرجاء إدخال قيم رقمية صحيحة لكل الحقول.");return;
  }
  const [initial,balance,equity,eod,peak,loss,daily,daystart,budget]=ids.map(num);
  if(initial<=0 || loss<=0 || daily<=0 || budget<=0 || balance<0 || equity<0 || eod<0 || peak<0){
    write("riskMessage","قيم الحساب غير صالحة. استخدم أرصدة موجبة وحدوداً أكبر من الصفر.");return;
  }
  const mode=document.getElementById("mode").value;
  const rawFloor=mode==="static" ? initial-loss : (mode==="eod" ? Math.max(initial,eod) : Math.max(initial,peak))-loss;
  // Illustration only: cap trailing floor at initial balance.
  const floor=mode==="static" ? rawFloor : Math.min(rawFloor,initial);
  const cushion=equity-floor,dayCushion=equity-(daystart-daily);
  const remaining=Math.min(cushion,dayCushion);
  const allowed=Math.max(0,Math.min(budget,remaining*.2));
  write("floor",usd(floor));write("cushion",usd(cushion));write("allowed",usd(allowed));
  const breached=remaining<=0;
  write("riskMessage", breached ? "تجاوزت أحد حدود الخسارة المُدخلة — يجب إيقاف فتح الصفقات." :
    "تقدير محلي فقط، بحاجز 20% من الحد الأقرب. لا يشمل العمولات والانزلاق والتزامات الشركة الفعلية ولا ينشئ أي أمر تداول.");
  document.getElementById("riskMessage").style.color=breached?"#f4b29d":"#8aa1ae";
}
form.addEventListener("submit",compute);
compute();

const datasetForm=document.getElementById("datasetForm");
const field=id=>document.getElementById(id);
datasetForm.addEventListener("submit",async e=>{
  e.preventDefault();
  const file=field("datasetFile").files[0];
  const status=field("dataLabStatus");
  const results=field("dataLabResults");
  const submit=field("analyzeBtn");
  results.hidden=true;
  if(!file){status.textContent="الرجاء اختيار ملف CSV حقيقي.";return;}
  if(file.size>1_000_000){status.textContent="الملف كبير لهذا الإصدار (الحد 1MB). قسّمه إلى نوافذ أصغر.";return;}
  submit.disabled=true;status.textContent="التحقق من البيانات وتشغيل المحاكاة التاريخية...";
  try{
    const text=await file.text();
    const lines=text.trim().split(/\r?\n/);
    const header=lines.shift().trim().replace(/^\uFEFF/,"").split(",").map(x=>x.trim());
    const required=["timestamp_utc","open","high","low","close","volume"];
    if(required.some(x=>!header.includes(x))) throw new Error("أعمدة CSV المطلوبة: "+required.join(", "));
    if(lines.length<7 || lines.length>7000)throw new Error("يلزم 7 إلى 7000 شمعة مكتملة.");
    let previous=-Infinity;
    const rows=lines.map((line,i)=>{
      const cols=line.split(",");
      if(cols.length!==header.length)throw new Error("تنسيق CSV غير صالح عند السطر "+(i+2));
      const get=x=>cols[header.indexOf(x)].trim();
      const stamp=get("timestamp_utc");
      if(!/(Z|[+-]\d{2}:\d{2})$/i.test(stamp))throw new Error("يجب كتابة الوقت مع المنطقة الزمنية UTC.");
      const date=new Date(stamp);
      if(Number.isNaN(date.getTime())||date.getTime()<=previous)throw new Error("تواريخ الشموع غير صحيحة أو غير مرتبة.");
      previous=date.getTime();
      const nums=required.slice(1).map(x=>Number(get(x)));
      if(nums.some(v=>!Number.isFinite(v)))throw new Error("قيمة سعر غير صالحة في السطر "+(i+2));
      const [o,h,l,c,v]=nums;
      if(l<=0||v<0||h<Math.max(o,l,c)||l>Math.min(o,c))throw new Error("شمعة OHLC غير منطقية في السطر "+(i+2));
      return {t:date.toISOString(),o,h,l,c,v};
    });
    const mode=field("mode").value;
    const response=await fetch("/api/research",{
      method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({bars:rows,instrument:field("instrument").value,
        fee:Number(field("tradeFee").value),risk:Number(field("budget").value),
        target:Number(field("profitTarget").value),
        starting:Number(field("initial").value),max_loss:Number(field("loss").value),
        daily_limit:Number(field("daily").value),
        mode:mode==="eod"?"eod_trailing":mode==="intraday"?"intraday_trailing":"static"})
    });
    const payload=await response.json();
    if(!response.ok)throw new Error(payload.error||"فشل خادم التحليل.");
    field("outBars").textContent=payload.bars.toLocaleString("en-US");
    field("outTrades").textContent=payload.trades.toLocaleString("en-US");
    field("outPnl").textContent=usd(Number(payload.net_pnl));
    field("outSummary").textContent=
      "جلسات: "+payload.sessions+" · مستبعدة لنقص البيانات: "+payload.skipped_sessions+
      " · Long: "+payload.long_trades+" · Short: "+payload.short_trades+
      " · خرق حدود الحساب: "+(payload.breached?"نعم":"لا")+
      " · الأهلية التقديرية: "+(payload.eligible_under_manual_rules?"نعم":"لا")+
      ". البيانات مرفوعة من المستخدم وغير متحقق منها بواسطة البورصة.";
    const body=field("outHistory");body.replaceChildren();
    for(const trade of payload.trade_history.slice(0,60)){
      const tr=document.createElement("tr");
      for(const val of [trade.side,trade.entry_time.replace("T"," ").slice(0,16),
                          String(trade.qty),usd(Number(trade.net_pnl)),trade.reason]){
        const td=document.createElement("td");td.textContent=val;tr.appendChild(td);
      }
      body.appendChild(tr);
    }
    results.hidden=false;
    status.textContent="اكتمل تحليل الملف: "+file.name+" — بحث تاريخي فقط، دون أي تداول أو ربط وسيط.";
  }catch(err){
    status.textContent="لم يُنفّذ التحليل: "+(err.message||"خطأ غير معروف")+
      ". إذا لم يستجب /api/research فراجع حالة نشر الـAPI على Vercel.";
  }finally{submit.disabled=false;}
});
