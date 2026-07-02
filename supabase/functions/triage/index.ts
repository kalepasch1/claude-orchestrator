// supabase/functions/triage - the cross-app optimization endpoint. ANY app (JS/TS/Go/Python) POSTs
// {app, operation, task_class, prompt, execute?} and gets back the cheapest capable route (and, if
// execute=true, the result). This is how the multi-model triage/optimization reaches every product
// without embedding runner code. Deploy: `supabase functions deploy triage`.
//
// Cost/quality is optimized by app_triage_review.py (perpetual bot review) which writes app_op_routes;
// this function honors a learned route when present, else falls back to the default cheapest tier.
//
// SECURITY: never log prompt payloads; only metadata is persisted to app_operations (no PII).
import { serve } from "https://deno.land/std@0.168.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const sb = createClient(SUPABASE_URL, SERVICE_KEY);

// ascending all-in cost; local/subscription first. Only providers whose keys exist are usable.
const TRANCHES: [string, string, number][] = [
  ["local", Deno.env.get("OLLAMA_MODEL") ?? "llama3.1", 5],
  ["deepseek", "deepseek-chat", 6],
  ["google", "gemini-2.0-flash", 6],
  ["openai", "gpt-4o-mini", 6],
];
const NEED: Record<string, number> = { mechanical: 5, qa: 6, review: 6, rating: 5, plan: 7 };

function available(): Set<string> {
  const s = new Set<string>();
  if (Deno.env.get("DEEPSEEK_API_KEY")) s.add("deepseek");
  if (Deno.env.get("GOOGLE_API_KEY")) s.add("google");
  if (Deno.env.get("OPENAI_API_KEY")) s.add("openai");
  if (Deno.env.get("OLLAMA_HOST")) s.add("local");
  return s;
}

async function learnedRoute(app: string, operation: string) {
  const { data } = await sb.from("app_op_routes").select("provider,model")
    .eq("app", app).eq("operation", operation).limit(1);
  return data && data[0]?.provider ? data[0] : null;
}

function policyРoute(taskClass: string) {
  const need = NEED[taskClass] ?? 6;
  const avail = available();
  for (const [prov, model, cap] of TRANCHES) if (avail.has(prov) && cap >= need) return { provider: prov, model };
  return { provider: "none", model: "" }; // caller keeps its own default (never more expensive)
}

serve(async (req) => {
  try {
    const { app, operation, task_class = "qa", prompt = "", execute = false } = await req.json();
    if (!app || !operation) return new Response(JSON.stringify({ error: "app+operation required" }), { status: 400 });
    const learned = await learnedRoute(app, operation);
    const route = learned ?? policyРoute(task_class);
    let text = "", cost = 0;
    if (execute && route.provider !== "none") {
      const r = await callProvider(route.provider, route.model, prompt);
      text = r.text; cost = r.cost;
    }
    // log metadata only (no prompt/PII)
    await sb.from("app_operations").insert({
      app, operation, task_class, provider: route.provider, model: route.model,
      prompt_chars: (prompt || "").length, cost_usd: cost, ok: true,
    });
    return new Response(JSON.stringify({ ...route, text, cost_usd: cost, source: learned ? "learned" : "policy" }),
      { headers: { "Content-Type": "application/json" } });
  } catch (e) {
    return new Response(JSON.stringify({ error: String(e) }), { status: 500 });
  }
});

async function callProvider(provider: string, model: string, prompt: string) {
  if (provider === "deepseek") {
    const r = await fetch("https://api.deepseek.com/chat/completions", {
      method: "POST", headers: { "Authorization": `Bearer ${Deno.env.get("DEEPSEEK_API_KEY")}`, "Content-Type": "application/json" },
      body: JSON.stringify({ model, messages: [{ role: "user", content: prompt }] }),
    });
    const d = await r.json();
    return { text: d.choices?.[0]?.message?.content ?? "", cost: 0 };
  }
  // google / openai / local adapters follow the same shape; omitted for brevity in this scaffold.
  return { text: "", cost: 0 };
}
