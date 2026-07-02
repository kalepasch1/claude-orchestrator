// GET /api/fleet/promotion-dossier — for each earned autonomy promotion, the full one-tap
// decision packet: VALUE (approvals/$ saved) + SAFETY (replayed false-positive rate) +
// BLAST (portfolio exposure). Recommends only when valuable AND proven-safe AND low-blast.
import { promotionDossier, DEFAULT_DOMAIN_POLICIES, type AdminDomain } from '@darwin/kernel/fleetAdmin';
import { serviceClient } from '../../utils/fleetSupabase';
import { ledgerEntries, resolvedHistory, exposureFor } from '../../utils/fleetReads';

export default defineEventHandler(async () => {
  const sb = serviceClient();
  const [entries, history] = await Promise.all([ledgerEntries(sb), resolvedHistory(sb)]);
  const ceilingOf = (d: AdminDomain) => DEFAULT_DOMAIN_POLICIES[d].ceiling;

  const dossiers = [];
  for (const entry of entries) {
    const exposure = await exposureFor(sb, entry.domain, entry.actionType);
    const d = promotionDossier(entry, history, exposure, ceilingOf);
    if (d) dossiers.push(d);
  }
  dossiers.sort((a, b) => (a.verdict === b.verdict ? b.value.dollarsAtRiskAvoided - a.value.dollarsAtRiskAvoided : a.verdict === 'recommend' ? -1 : 1));
  return { dossiers, total: dossiers.length, recommended: dossiers.filter((d) => d.verdict === 'recommend').length };
});
