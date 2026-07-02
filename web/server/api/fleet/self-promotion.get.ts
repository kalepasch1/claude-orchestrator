// GET /api/fleet/self-promotion — the closed-loop batch: every earned promotion assembled
// into an evidence-backed dossier, filtered to the replay-safe + low-blast set, as ONE
// accept-all card. This is what moves the autonomy rate on its own.
import { assembleSelfPromotionBatch, DEFAULT_DOMAIN_POLICIES, type AdminDomain } from '@darwin/kernel/fleetAdmin';
import { serviceClient } from '../../utils/fleetSupabase';
import { ledgerEntries, resolvedHistory, exposureFor } from '../../utils/fleetReads';

export default defineEventHandler(async () => {
  const sb = serviceClient();
  const [entries, history] = await Promise.all([ledgerEntries(sb), resolvedHistory(sb)]);
  // Pre-fetch exposure per candidate type so the (sync) assembler can size blast.
  const exposureByKey = new Map<string, any[]>();
  for (const e of entries) exposureByKey.set(`${e.domain}::${e.actionType}`, await exposureFor(sb, e.domain, e.actionType));
  const batch = assembleSelfPromotionBatch({
    entries, history,
    exposureFor: (d, t) => exposureByKey.get(`${d}::${t}`) ?? [],
    ceilingOf: (d: AdminDomain) => DEFAULT_DOMAIN_POLICIES[d].ceiling,
  });
  return batch;
});
