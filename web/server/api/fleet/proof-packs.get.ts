// GET /api/fleet/proof-packs - shared proof/deployment receipts across portfolio apps.
import { serviceClient } from '../../utils/fleetSupabase';

export default defineEventHandler(async () => {
  const sb = serviceClient();
  const { data: brainRows, error: brainError } = await sb
    .from('common_brain_deployments')
    .select('product,task_slug,status,outcome,tokens_avoided,minutes_avoided,review_failures,rollback,metadata,updated_at,created_at')
    .order('updated_at', { ascending: false })
    .limit(50);

  const { data: receiptRows } = await sb
    .from('fleet_receipts')
    .select('id,chain,seq,digest,decision,reason,at')
    .order('at', { ascending: false })
    .limit(20);

  return {
    commonBrain: brainRows ?? [],
    receipts: receiptRows ?? [],
    error: brainError?.message ?? null,
    generatedAt: new Date().toISOString(),
  };
});
