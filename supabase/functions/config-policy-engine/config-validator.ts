// Validator module: delegates to the DB rule engine via RPC.
// No credentials hardcoded — all enforcement lives in the DB triggers/functions.

import { SupabaseClient } from "https://esm.sh/@supabase/supabase-js@2";

export interface ValidationResult {
  valid: boolean;
  key: string;
  error?: string;
}

export interface BulkValidationResult {
  rejected: string[];
  valid: boolean;
}

export async function validateConfigKey(
  sb: SupabaseClient,
  key: string,
): Promise<ValidationResult> {
  const { data, error } = await sb.rpc("validate_config_key", { p_key: key });
  if (error) return { valid: false, key, error: error.message };
  return { valid: !!data, key };
}

export async function validateConfigBulk(
  sb: SupabaseClient,
  config: Record<string, string>,
): Promise<BulkValidationResult> {
  const { data, error } = await sb.rpc("apply_config_policy", { p_config: config });
  if (error) return { rejected: Object.keys(config), valid: false };
  const rejected = (data as string[]) ?? [];
  return { rejected, valid: rejected.length === 0 };
}
