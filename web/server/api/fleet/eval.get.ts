// GET /api/fleet/eval — scores the plane against a held-out slice of the resolved-decision log:
// the GATE's auto-vs-human calls (false auto-runs are the safety-critical metric) and the learned
// decision model. Run this before trusting a promotion — precision/recall on real labels.
import { splitHoldout, trainDecisionModel, samplesFromResolved, evalDecisionModel, evalGate, governFleetAction, fleetAdminConstitution, type ResolvedCase, type AdminAction } from '@darwin/kernel/fleetAdmin';
import { serviceClient } from '../../utils/fleetSupabase';
import { resolvedHistory } from '../../utils/fleetReads';

export default defineEventHandler(async () => {
  const sb = serviceClient();
  const cases = await resolvedHistory(sb);
  if (cases.length < 20) return { ok: false, reason: 'insufficient_labeled_history', have: cases.length };

  const { train, test } = splitHoldout(cases, 5);
  const model = trainDecisionModel(samplesFromResolved(train));
  const modelScore = evalDecisionModel(model, test);

  // Gate eval: re-govern each held-out case's shape and compare auto-vs-human to the outcome.
  const constitution = fleetAdminConstitution();
  const gateCases = test.map((c: ResolvedCase) => {
    const action: AdminAction = { id: 'eval', product: 'orchestrator', domain: c.domain, type: c.type, actor: 'eval', confidence: 0.95, reversibility: c.reversibility, blastRadius: c.blastRadius, intent: 'eval', amountUsd: c.amountUsd, at: c.at };
    const v = governFleetAction({ action, constitution });
    return { tier: v.tier, decisionAllow: v.decision === 'allow', outcome: c.outcome };
  });
  const gateScore = evalGate(gateCases);

  return { ok: true, trainSize: train.length, testSize: test.length, gate: gateScore, decisionModel: modelScore };
});
