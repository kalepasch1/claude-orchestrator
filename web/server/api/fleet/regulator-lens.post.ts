// POST /api/fleet/regulator-lens  { query }
// Regulator co-pilot: answer a compliance question in English over the decision log — filtered,
// PII-redacted, and proof-linked. Read-only; subject identifiers are hashed; each match carries
// its signed receipt digest for offline verification.
import { regulatorQuery, type DecisionRecord } from '@darwin/kernel/fleetAdmin';
import { serviceClient } from '../../utils/fleetSupabase';

export default defineEventHandler(async (event) => {
  const { query } = (await readBody(event)) as { query?: string };
  if (!query) throw createError({ statusCode: 400, message: 'query required' });
  const sb = serviceClient();
  const { data } = await sb
    .from('fleet_admin_actions')
    .select('id,product,domain,type,tier,decision,amount_usd,subject_id,created_at,receipt_digest')
    .not('decision', 'is', null).limit(10000);
  const records: DecisionRecord[] = (data ?? []).map((r: any) => ({
    actionId: r.id, product: r.product, domain: r.domain, type: r.type, tier: r.tier ?? 'human', decision: r.decision,
    amountUsd: r.amount_usd ?? undefined, subjectId: r.subject_id ?? undefined, at: r.created_at, receiptDigest: r.receipt_digest ?? '',
  }));
  return regulatorQuery(query, records);
});
