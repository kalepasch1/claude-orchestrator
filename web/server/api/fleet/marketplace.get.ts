// GET /api/fleet/marketplace — this org's PUBLISHABLE governance artifacts, signed + ready to
// list on the shared market: its current constitution and a DP-anonymized precedent pack. Other
// orgs discover + install these so a new company inherits mature policy on day one.
import { signListing, verifyListing, fleetAdminConstitution, buildFederatedPrecedent } from '@darwin/kernel/fleetAdmin';
import { serviceClient } from '../../utils/fleetSupabase';
import { appTypeStats } from '../../utils/fleetReads';

export default defineEventHandler(async () => {
  const sb = serviceClient();
  const constitution = fleetAdminConstitution();
  const precedent = buildFederatedPrecedent(await appTypeStats(sb)); // DP-aggregated; safe to share

  const listings = [
    signListing({
      id: 'fleet-constitution-v' + constitution.version, kind: 'constitution', title: 'Fleet Admin Constitution', owner: 'this-org', version: String(constitution.version),
      tags: ['admin', 'governance', 'billing', 'infra', 'users_access', 'trust_safety'],
      payload: { alwaysEscalate: constitution.alwaysEscalate, rules: constitution.rules.map((r) => ({ id: r.id, text: r.text, effect: r.effect, appliesTo: r.appliesTo })) },
      publishedAt: new Date().toISOString(),
    }),
    signListing({
      id: 'fleet-precedent-pack', kind: 'precedent_pack', title: 'Admin precedent pack (DP-anonymized)', owner: 'this-org', version: '1.0.0',
      tags: ['admin', 'precedent', 'autonomy'], payload: { precedent }, publishedAt: new Date().toISOString(),
    }),
  ];
  return { listings, allVerify: listings.every(verifyListing) };
});
