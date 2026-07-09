// Unit tests for config-validator.ts — mocks the Supabase client, no real DB needed.
// Run: deno test supabase/functions/config-policy-engine/tests/

import { assertEquals } from "https://deno.land/std@0.168.0/testing/asserts.ts";
import { validateConfigKey, validateConfigBulk } from "../config-validator.ts";
import type { SupabaseClient } from "https://esm.sh/@supabase/supabase-js@2";

function mockSb(rpcData: unknown, rpcError?: { message: string }): SupabaseClient {
  return {
    rpc: (_fn: string, _args: unknown) =>
      Promise.resolve({ data: rpcData, error: rpcError ?? null }),
  } as unknown as SupabaseClient;
}

// validateConfigKey

Deno.test("validateConfigKey: safe key returns valid=true", async () => {
  const r = await validateConfigKey(mockSb(true), "ORCH_AUTO_PULL");
  assertEquals(r.valid, true);
  assertEquals(r.key, "ORCH_AUTO_PULL");
  assertEquals(r.error, undefined);
});

Deno.test("validateConfigKey: unsafe key returns valid=false", async () => {
  const r = await validateConfigKey(mockSb(false), "MY_API_KEY");
  assertEquals(r.valid, false);
  assertEquals(r.key, "MY_API_KEY");
});

Deno.test("validateConfigKey: db error returns valid=false with error message", async () => {
  const r = await validateConfigKey(mockSb(null, { message: "connection error" }), "ORCH_FOO");
  assertEquals(r.valid, false);
  assertEquals(r.error, "connection error");
});

Deno.test("validateConfigKey: null data treated as invalid", async () => {
  const r = await validateConfigKey(mockSb(null), "ORCH_FOO");
  assertEquals(r.valid, false);
});

// validateConfigBulk

Deno.test("validateConfigBulk: all-safe config returns empty rejected", async () => {
  const r = await validateConfigBulk(mockSb([]), { ORCH_FOO: "bar", MAX_PARALLEL: "4" });
  assertEquals(r.valid, true);
  assertEquals(r.rejected, []);
});

Deno.test("validateConfigBulk: some unsafe returns rejected list", async () => {
  const r = await validateConfigBulk(mockSb(["MY_API_KEY"]), {
    ORCH_FOO: "bar",
    MY_API_KEY: "secret",
  });
  assertEquals(r.valid, false);
  assertEquals(r.rejected, ["MY_API_KEY"]);
});

Deno.test("validateConfigBulk: db error rejects all keys", async () => {
  const config = { ORCH_FOO: "bar", DEPLOY_ENV: "prod" };
  const r = await validateConfigBulk(mockSb(null, { message: "timeout" }), config);
  assertEquals(r.valid, false);
  assertEquals(r.rejected.length, Object.keys(config).length);
});

Deno.test("validateConfigBulk: empty config returns valid=true", async () => {
  const r = await validateConfigBulk(mockSb([]), {});
  assertEquals(r.valid, true);
  assertEquals(r.rejected, []);
});

Deno.test("validateConfigBulk: null rpc data with no error treated as no rejections", async () => {
  // DB returns null only in pathological cases; null ?? [] = [], so no keys rejected.
  const r = await validateConfigBulk(mockSb(null), { ORCH_FOO: "bar" });
  assertEquals(r.valid, true);
  assertEquals(r.rejected, []);
});
