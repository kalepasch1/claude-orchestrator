// GET /api/fleet/promotions — the reverse auction: promotion offers the flywheel has
// earned, each with dollars + approvals-saved attached, ranked by modelled value.
import { auctionBoard, DEFAULT_DOMAIN_POLICIES, type LedgerEntry, type AdminDomain } from '@darwin/kernel/fleetAdmin';
import { serviceClient } from '../../utils/fleetSupabase';

export default defineEventHandler(async () => {
  const sb = serviceClient();
  const { data } = await sb.from('fleet_autonomy_ledger').select('*');
  const entries: LedgerEntry[] = (data ?? []).map((r: any) => ({
    actionType: r.action_type, domain: r.domain, streak: r.streak, total: r.total,
    cleanApprovals: r.clean_approvals, edits: r.edits, rejections: r.rejections,
    promotedTier: r.promoted_tier ?? undefined, promotedAt: r.promoted_at ?? undefined, updatedAt: r.updated_at,
  }));
  const offers = auctionBoard(entries, (d: AdminDomain) => DEFAULT_DOMAIN_POLICIES[d].ceiling);
  return { offers, total: offers.length };
});
