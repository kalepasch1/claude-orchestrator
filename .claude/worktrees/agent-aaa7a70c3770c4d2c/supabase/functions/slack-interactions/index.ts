// slack-interactions - receives Approve/Deny button clicks from Slack and updates the
// approvals row. Set this function's URL as the Slack app's "Interactivity Request URL".
//
// Secret: SLACK_SIGNING_SECRET (verify requests). SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY auto.
import { serve } from "https://deno.land/std@0.224.0/http/server.ts";
import { createHmac } from "node:crypto";

const SIGNING = Deno.env.get("SLACK_SIGNING_SECRET") ?? "";
const SB_URL = Deno.env.get("SUPABASE_URL")!;
const SB_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

function verify(ts: string, sig: string, raw: string): boolean {
  if (!SIGNING) return true; // allow if unset (dev); set it in prod
  if (Math.abs(Date.now() / 1000 - Number(ts)) > 300) return false;
  const mac = "v0=" + createHmac("sha256", SIGNING).update(`v0:${ts}:${raw}`).digest("hex");
  return mac === sig;
}

serve(async (req) => {
  const raw = await req.text();
  const ts = req.headers.get("x-slack-request-timestamp") ?? "";
  const sig = req.headers.get("x-slack-signature") ?? "";
  if (!verify(ts, sig, raw)) return new Response("bad signature", { status: 401 });

  const payload = JSON.parse(decodeURIComponent(raw.replace(/^payload=/, "")));
  const action = payload.actions?.[0];
  const id = action?.value;
  const decision = action?.action_id === "approve" ? "approved" : "denied";
  const who = payload.user?.username ?? payload.user?.name ?? "slack";

  await fetch(`${SB_URL}/rest/v1/approvals?id=eq.${id}`, {
    method: "PATCH",
    headers: { apikey: SB_KEY, Authorization: `Bearer ${SB_KEY}`,
               "Content-Type": "application/json", Prefer: "return=minimal" },
    body: JSON.stringify({ status: decision, decided_at: new Date().toISOString(), decided_by: who }),
  });

  return new Response(JSON.stringify({
    replace_original: true,
    text: `${decision === "approved" ? "✅ Approved" : "🛑 Denied"} by ${who}`,
  }), { headers: { "Content-Type": "application/json" } });
});
