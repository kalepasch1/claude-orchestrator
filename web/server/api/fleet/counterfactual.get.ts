// GET /api/fleet/counterfactual — runs "what would Bear have done?" on every auto action in
// shadow. Divergences (auto-ran something the model says he'd likely reject/edit) are early
// regret signals that don't wait for a chargeback.
import { buildApproverProfile, counterfactualReview, type AutoDecisionRef } from '@darwin/kernel/fleetAdmin';
import { serviceClient } from '../../utils/fleetSupabase';
import { approverDecisions } from '../../utils/fleetReads';

export default defineEventHandler(async () => {
  const sb = serviceClient();
  const [profile, { data }] = await Promise.all([
    approverDecisions(sb).then(buildApproverProfile),
    sb.from('fleet_admin_actions').select('id,domain,type').eq('tier', 'auto').eq('executed', true).limit(5000),
  ]);
  const autos: AutoDecisionRef[] = (data ?? []).map((r: any) => ({ actionId: r.id, domain: r.domain, actionType: r.type }));
  return counterfactualReview(autos, profile);
});
