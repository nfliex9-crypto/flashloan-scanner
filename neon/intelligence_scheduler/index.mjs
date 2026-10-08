// AEGIS daily intelligence scheduler. Neon schedule triggers this private bridge.
export default {
  async fetch(request) {
    if (request.method !== "POST" || !request.headers.get("x-neon-trigger-invocation-id")) {
      return Response.json({ok:false,error:"trigger_only"},{status:403});
    }
    const target=process.env.TARGET_URL;
    const secret=process.env.PAPER_TICK_SECRET;
    const bypass=process.env.VERCEL_BYPASS_SECRET;
    if (!target || !secret || !bypass) {
      return Response.json({ok:false,error:"not_configured"},{status:500});
    }
    const response=await fetch(target,{
      method:"POST",
      headers:{
        "Authorization":"Bearer "+secret,
        "x-vercel-protection-bypass":bypass,
        "Content-Type":"application/json"
      },
      body:"{}",
      signal:AbortSignal.timeout(25000)
    });
    const raw=await response.text();
    console.log(JSON.stringify({kind:"finra_daily",status:response.status,success:response.ok}));
    return new Response(raw,{status:response.ok?200:502,headers:{"Content-Type":"application/json"}});
  }
};
