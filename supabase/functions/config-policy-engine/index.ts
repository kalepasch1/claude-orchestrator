// config-policy-engine: HTTP API over fleet_config with DB-enforced safety rules.
// GET  ?key=ORCH_FOO           → {valid, key} — validate without writing
// POST {key, value[, note, updated_by]} → upsert into fleet_config (trigger rejects unsafe keys)
// Deploy: `supabase functions deploy config-policy-engine`

import { serve } from "https://deno.land/std@0.168.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";
import { validateConfigKey } from "./config-validator.ts";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

const JSON_HEADERS = {
  "Content-Type": "application/json",
  "Access-Control-Allow-Origin": "*",
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: JSON_HEADERS });
}

serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: JSON_HEADERS });
  }

  const sb = createClient(SUPABASE_URL, SERVICE_KEY);

  try {
    if (req.method === "GET") {
      const key = new URL(req.url).searchParams.get("key");
      if (!key) return json({ error: "key param required" }, 400);
      const result = await validateConfigKey(sb, key);
      return json(result, result.valid ? 200 : 400);
    }

    if (req.method === "POST") {
      const body = await req.json() as {
        key?: string; value?: string; note?: string; updated_by?: string;
      };
      const { key, value, note, updated_by } = body;

      if (!key || value === undefined) {
        return json({ error: "key and value are required" }, 400);
      }

      // Fast-fail with a clear error before hitting the DB trigger.
      const check = await validateConfigKey(sb, key);
      if (!check.valid) {
        return json({ error: `key '${key}' rejected by fleet safety policy`, key }, 400);
      }

      const row: Record<string, string> = { key, value: String(value), updated_at: new Date().toISOString() };
      if (note) row.note = note;
      if (updated_by) row.updated_by = updated_by;

      const { error } = await sb.from("fleet_config").upsert(row);
      if (error) return json({ error: error.message }, 400);

      return json({ ok: true, key, value });
    }

    return json({ error: "method not allowed" }, 405);
  } catch (e) {
    return json({ error: String(e) }, 500);
  }
});
