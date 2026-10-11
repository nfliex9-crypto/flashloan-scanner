"use strict";
(() => {
  const $=id=>document.getElementById(id);
  if(!$('chartReader'))return;
  let snapshots=[],selected='',busy=false,analyzing=false,lastGoldRefresh=0;
  const fmt=n=>Number.isFinite(n)?new Intl.NumberFormat('en-US',{maximumFractionDigits:2}).format(n):'—';
  const time=s=>s?new Date(s).toLocaleString('ar-BE',{timeZone:'Europe/Brussels'}):'—';
  const labels={STREAMING:'استقبال مباشر',OBSERVED_DELAY_UNVERIFIED:'قراءة مستلمة · تأخير المزوّد غير مؤكد',DISCONNECTED:'انقطع تحديث المصدر',STALE_MARKET_DATA:'بيانات سوق قديمة / جلسة مغلقة',CLOCK_MISMATCH:'اختلاف التوقيت',BULLISH:'صاعد',BEARISH:'هابط',MIXED:'مختلط',NEUTRAL:'محايد',ABOVE_RANGE:'فوق النطاق',BELOW_RANGE:'تحت النطاق',IN_RANGE:'داخل النطاق',UNREADABLE:'الصورة غير واضحة'};
  function text(id,value){$(id).textContent=value}
  function candles(bars){
    const canvas=$('readerCanvas'),c=canvas.getContext('2d'),w=canvas.width,h=canvas.height;
    c.clearRect(0,0,w,h);if(!bars?.length)return;
    const data=bars.slice(-65),hi=Math.max(...data.map(b=>b.high)),lo=Math.min(...data.map(b=>b.low)),span=hi-lo||hi*.001;
    const y=p=>h-45-(p-lo)/span*(h-80),step=(w-100)/data.length;
    c.font='12px monospace';
    for(let i=0;i<5;i++){let p=lo+span*i/4;c.strokeStyle='#203145';c.beginPath();c.moveTo(5,y(p));c.lineTo(w-85,y(p));c.stroke();c.fillStyle='#95abc0';c.fillText(fmt(p),w-80,y(p)+4)}
    data.forEach((b,i)=>{let x=10+i*step;c.fillStyle=c.strokeStyle=b.close>=b.open?'#42d8a8':'#ef7787';c.lineWidth=1.5;c.beginPath();c.moveTo(x,y(b.high));c.lineTo(x,y(b.low));c.stroke();let a=y(Math.max(b.open,b.close)),z=y(Math.min(b.open,b.close));c.fillRect(x-step*.28,a,step*.56,Math.max(1,z-a))});
    c.fillStyle='#95abc0';c.fillText(new Date(data[0].time*1000).toLocaleString('en-GB',{timeZone:'Europe/Brussels'}),8,h-12);
    c.fillText(new Date(data.at(-1).time*1000).toLocaleString('en-GB',{timeZone:'Europe/Brussels'}),w-240,h-12);
  }
  function render(){
    const d=snapshots.find(s=>s.source_id===selected)||snapshots[0];if(!d)return;selected=d.source_id;
    $('readerSource').value=selected;
    const a=d.analysis||{},fresh=d.freshness||{};
    text('readerState',labels[fresh.state]||fresh.state);$('readerState').dataset.state=fresh.state;
    text('readerPrice',fmt(d.bars.at(-1)?.close));text('readerInstrument',d.symbol+' · '+d.interval_minutes+'m');
    candles(d.bars);
    text('readerTime',d.source+' · آخر استلام: '+time(d.observed_at)+' · منذ '+fmt(fresh.capture_age_seconds)+' ثانية');
    $('readerObservers').replaceChildren();
    for(const o of a.observers||[]){const row=document.createElement('div'),name=document.createElement('span'),state=document.createElement('strong');name.textContent={trend:'محلل الاتجاه',momentum:'محلل الزخم',structure:'محلل المستويات'}[o.id]||o.id;state.textContent=labels[o.state]||o.state;row.append(name,state);$('readerObservers').append(row)}
    $('readerMetrics').replaceChildren();
    for(const [k,name] of [['ema20','EMA 20'],['ema50','EMA 50'],['rsi14','RSI 14'],['atr14','ATR 14'],['support20','أدنى النطاق السابق'],['resistance20','أعلى النطاق السابق']]){const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=name;dd.textContent=fmt(a[k]);$('readerMetrics').append(dt,dd)}
    text('readerQuality',(a.bar_count||0)+' شمعة مغلقة · '+(a.gap_count||0)+' فجوة زمنية · '+(d.instrument_kind==='GOLD_FUTURES'?'عقد ذهب آجل مستقل عن XAUUSD':'مصدر السعر: '+d.symbol)+'\nالشمعة الأخيرة قد تتغير حتى إغلاقها. هذه قراءة تحليلية وليست صفقة منفذة.');
    const img=d.last_image;
    $('readerCapture').hidden=!img;
    if(img){$('readerCapture').src='data:image/png;base64,'+img.image_png;text('readerCaptureState','لقطة TradingView: '+time(img.context.observed_at))}
    else {text('readerCaptureState',d.source==='TRADINGVIEW_DESKTOP'?'بانتظار صورة الشارت التالية من اللابتوب.':'صورة تحليل هذا المصدر تُرسم من الشموع أعلاه. لقطة TradingView الأصلية تظهر بعد تشغيل وصلة اللابتوب.');$('readerCapture').removeAttribute('src')}
    const vision=d.vision||{},report=vision.report;
    text('readerVisionState',report?'قراءة الصورة: '+(labels[report.bias]||report.bias):'بانتظار أول تحليل بصري لهذا الشارت');
    text('readerVisionText',report?[report.observations,report.numeric_agreement,report.limitations].join('\n\n'):'التحليل البصري يقارن الصورة بالأرقام المسجلة في نفس اللقطة.');
    text('readerVisionTime',report?report.model+' · لقطة '+time(vision.observed_at)+' · '+(report.image_kind==='TRADINGVIEW_CHART_CROP'?'صورة TradingView':'رسم AEGIS لبيانات المصدر'):'');
  }
  async function refresh(gold=false){
    if(busy)return;busy=true;
    if(gold)lastGoldRefresh=Date.now();
    try {const r=await fetch('/api/stage3?chart='+(gold?'gold':'1')+(selected?'&source='+encodeURIComponent(selected):''),{cache:'no-store'}),d=await r.json();if(!r.ok||!d.ok)throw Error('قارئ الشارت غير متاح؛ جاري انتظار المصدر.');
      snapshots=d.snapshots||[];const options=$('readerSource');options.replaceChildren();
      (d.sources||[]).forEach(s=>{let o=document.createElement('option');o.value=s.source_id;o.textContent=s.symbol+' · '+s.interval_minutes+'m · '+s.source;options.append(o)});
      if(gold){const g=snapshots.find(s=>s.source==='TWELVE_DATA_REST');if(g)selected=g.source_id;else text('readerActionStatus','مصدر الذهب: '+(d.gold_refresh?.state||'غير متاح'))}
      if(!snapshots.length)text('readerState','بانتظار أول لقطة موثّقة');else render();
    }catch(e){text('readerState',e.message)}finally{busy=false}
  }
  async function analyze(){
    if(analyzing||!selected)return;const secret=$('readerToken').value;
    if(secret.length<32){text('readerActionStatus','أدخل مفتاح قارئ AEGIS للطلب الخاص؛ ليس كلمة مرور TradingView.');return}
    analyzing=true;$('readerAnalyze').disabled=true;text('readerActionStatus','يجري تحليل صورة الشارت والأرقام…');
    try{const raw=JSON.stringify({action:'analyze',source_id:selected}),ts=Math.floor(Date.now()/1000).toString(),enc=new TextEncoder();
      const key=await crypto.subtle.importKey('raw',enc.encode(secret),{name:'HMAC',hash:'SHA-256'},false,['sign']);
      const sig=await crypto.subtle.sign('HMAC',key,enc.encode(ts+'.'+raw));const hex=Array.from(new Uint8Array(sig),b=>b.toString(16).padStart(2,'0')).join('');
      const r=await fetch('/api/stage3?chart=1',{method:'POST',headers:{'Content-Type':'application/json','X-Aegis-Timestamp':ts,'X-Aegis-Signature':hex},body:raw}),d=await r.json();
      if(!r.ok||!d.ok)throw Error(d.error||'تعذر تحليل الصورة');text('readerActionStatus','اكتمل التحليل وحُفظ مع مصدره ووقت اللقطة.');await refresh();
    }catch(e){text('readerActionStatus',e.message)}finally{analyzing=false;$('readerAnalyze').disabled=false}
  }
  $('readerSource').addEventListener('change',e=>{selected=e.target.value;refresh()});
  $('readerGold').addEventListener('click',()=>refresh(true));$('readerAnalyze').addEventListener('click',analyze);
  refresh();setInterval(()=>{if(!document.hidden)refresh(selected.startsWith('TWELVE_DATA_REST:')&&Date.now()-lastGoldRefresh>60000)},5000);
})();
