const TARGET_URL = process.env.TARGET_URL;
const PAPER_TICK_SECRET = process.env.PAPER_TICK_SECRET;
const VERCEL_BYPASS_SECRET = process.env.VERCEL_BYPASS_SECRET;

export default {
  async fetch(request) {
    if (request.method !== "POST") {
      return new Response("Method Not Allowed", { status: 405 });
    }

    const invocationId = request.headers.get("x-neon-trigger-invocation-id");
    if (!invocationId) {
      return Response.json({ ok: false, error: "trigger_only" }, { status: 403 });
    }

    if (!TARGET_URL || !PAPER_TICK_SECRET || !VERCEL_BYPASS_SECRET) {
      return Response.json({ ok: false, error: "scheduler_not_configured" }, { status: 500 });
    }

    const body = await request.json();
    const scheduledAt = body?.data?.scheduled_at || new Date().toISOString();

    const response = await fetch(TARGET_URL, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "authorization": `Bearer ${PAPER_TICK_SECRET}`,
        "x-vercel-protection-bypass": VERCEL_BYPASS_SECRET,
        "x-aegis-scheduler": "neon-hourly",
      },
      body: JSON.stringify({
        scheduled_at: scheduledAt,
        neon_invocation_id: invocationId,
      }),
      signal: AbortSignal.timeout(25000),
    });

    const text = await response.text();
    let payload;
    try {
      payload = JSON.parse(text);
    } catch {
      payload = { raw: text.slice(0, 1000) };
    }

    console.log(JSON.stringify({
      event: "aegis_scheduler",
      scheduled_at: scheduledAt,
      target_status: response.status,
      target_ok: response.ok,
      run_id: payload?.run_id || null,
    }));

    return Response.json(
      {
        ok: response.ok,
        scheduled_at: scheduledAt,
        target_status: response.status,
        target: payload,
      },
      { status: response.ok ? 200 : 502 }
    );
  },
};
