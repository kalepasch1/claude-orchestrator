// GET /api/fleet/decision-model — trains the learned admin-decision policy on the resolved
// corpus and returns its weights + a few sample predictions. The corpus is the moat; this is the
// servable model (other orgs can consume its predictions as a capability).
import { trainDecisionModel, samplesFromResolved, predictApprove } from '@darwin/kernel/fleetAdmin';
import { serviceClient } from '../../utils/fleetSupabase';
import { resolvedHistory } from '../../utils/fleetReads';

export default defineEventHandler(async () => {
  const sb = serviceClient();
  const cases = await resolvedHistory(sb);
  const model = trainDecisionModel(samplesFromResolved(cases));
  const samplePredictions = {
    small_reversible_refund: predictApprove(model, { domain: 'billing', type: 'billing:issue_refund', amountUsd: 10, reversibility: 'reversible', blastRadius: 'single' }),
    large_irreversible_fleet: predictApprove(model, { domain: 'billing', type: 'billing:issue_refund', amountUsd: 5000, reversibility: 'irreversible', blastRadius: 'fleet' }),
  };
  return { trainedOn: model.samples, weights: model.weights, samplePredictions };
});
