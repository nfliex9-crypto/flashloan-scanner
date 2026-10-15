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
