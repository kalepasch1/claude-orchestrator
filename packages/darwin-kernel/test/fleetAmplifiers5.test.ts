import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  assembleSelfPromotionBatch,
  projectNewApp,
  fuseReputation,
  reputationAdjustedTier,
  commandIncident,
  buildAutonomyAttestation,
  verifyAutonomyAttestation,
  replayWindow,
  attributeDrift,
  fleetAdminConstitution,
  DEFAULT_DOMAIN_POLICIES,
  AdminSeverity,
  type LedgerEntry,
  type ResolvedCase,
  type ExposureRecord,
  type ExpectedType,
  type SubjectSignal,
  type AdminEvent,
  type AdminAction,
  type AdminDomain,
} from '../src/fleetAdmin/index.ts';

const now = '2026-07-01T00:00:00.000Z';
const ceilingOf = (d: AdminDomain) => DEFAULT_DOMAIN_POLICIES[d].ceiling;
function rc(outcome: ResolvedCase['outcome'], amountUsd = 9): ResolvedCase {
  return { domain: 'billing', type: 'billing:issue_refund', amountUsd, reversibility: 'reversible', blastRadius: 'single', outcome, at: now };
}

// ---------- self-promotion cycle ----------
test('self-promotion batch: clean history yields an accept-all-safe set', () => {
  const entries: LedgerEntry[] = [{ actionType: 'billing:issue_refund', domain: 'billing', streak: 25, total: 25, cleanApprovals: 25, edits: 0, rejections: 0, updatedAt: now }];
  const history = Array.from({ length: 30 }, () => rc('approve'));
  const exposure: ExposureRecord[] = [{ product: 'galop', amountUsd: 10, at: '2026-06-01T00:00:00Z' }, { product: 'pareto', amountUsd: 12, at: '2026-06-02T00:00:00Z' }];
  const batch = assembleSelfPromotionBatch({ entries, history, exposureFor: () => exposure, ceilingOf });
  assert.equal(batch.recommended.length, 1);
  assert.equal(batch.aggregateRegressions, 0);
  assert.equal(batch.safeToAcceptAll, true);
  assert.ok(batch.totalApprovalsSaved > 0);
});
test('self-promotion holds a promotion with replayed regressions', () => {
  const entries: LedgerEntry[] = [{ actionType: 'billing:issue_refund', domain: 'billing', streak: 25, total: 25, cleanApprovals: 25, edits: 0, rejections: 0, updatedAt: now }];
  const dirty = [...Array.from({ length: 20 }, () => rc('approve')), ...Array.from({ length: 10 }, () => rc('reject'))];
  const batch = assembleSelfPromotionBatch({ entries, history: dirty, exposureFor: () => [{ product: 'galop', amountUsd: 10, at: now }], ceilingOf });
  assert.equal(batch.recommended.length, 0);
  assert.equal(batch.held.length, 1);
});

// ---------- world model ----------
test('world model projects a new app from federated priors', () => {
  const expected: ExpectedType[] = [
    { domain: 'billing', actionType: 'billing:issue_refund', dailyVolume: 100, expectedCleanRate: 0.98, avgAmountUsd: 10 },
    { domain: 'trust_safety', actionType: 'trust_safety:terminate_account', dailyVolume: 5, expectedCleanRate: 0.4 },
  ];
  const seed = { 'billing::billing:issue_refund': 'auto' as const };
  const proj = projectNewApp({ product: 'newco', expected, federatedSeed: seed, ceilingOf });
  assert.ok(proj.projectedAutonomyRate > 0.9); // refund volume dominates + borrows auto
  assert.ok(proj.autoTypes.includes('billing::billing:issue_refund'));
  assert.ok(proj.treasury.netUsd !== 0);
});

// ---------- subject reputation ----------
test('reputation fuses cross-app signals + caps autonomy for risky subjects', () => {
  const signals: SubjectSignal[] = [
    { subjectId: 'u1', product: 'galop', kind: 'fraud', at: now },
    { subjectId: 'u1', product: 'pareto', kind: 'chargeback', at: now },
    { subjectId: 'u2', product: 'apparently', kind: 'verified', at: now },
  ];
  const reps = fuseReputation(signals);
  const u1 = reps.find((r) => r.subjectId === 'u1')!;
  assert.ok(u1.score < 0.3);
  assert.equal(u1.appsSeen.length, 2);
  assert.equal(reputationAdjustedTier('auto', u1).tier, 'human'); // risky → forced human
  const u2 = reps.find((r) => r.subjectId === 'u2')!;
  assert.equal(reputationAdjustedTier('auto', u2).tier, 'auto'); // trusted → unchanged
  assert.equal(reputationAdjustedTier('auto', undefined).tier, 'auto'); // no rep → unchanged
});

// ---------- incident commander ----------
test('incident commander answers root-cause + fix in English', () => {
  const base = Date.parse(now);
  const events: AdminEvent[] = [
    { id: 'e1', product: 'apparently', domain: 'infra', category: 'outage', severity: AdminSeverity.BLOCKING, title: 'o', summary: '', at: new Date(base).toISOString(), details: { provider: 'supabase-east' } },
    { id: 'e2', product: 'pareto', domain: 'infra', category: 'error_spike', severity: AdminSeverity.URGENT, title: 'e', summary: '', at: new Date(base + 60000).toISOString(), details: { provider: 'supabase-east' } },
  ];
  const ans = commandIncident('what is the root cause of the supabase-east incident?', events);
  assert.equal(ans.intent, 'root_cause');
  assert.ok(ans.affectedProducts.includes('apparently') && ans.affectedProducts.includes('pareto'));
  const fix = commandIncident('what is the one fix?', events);
  assert.equal(fix.intent, 'fix');
  assert.ok(fix.suggestedFix);
});

// ---------- autonomy attestation ----------
test('autonomy attestation is signed, stateless-verifiable, and graded', () => {
  const good = buildAutonomyAttestation({ issuedAt: now, periodDays: 7, answeredFromPlaneRate: 0.8, totalDecisions: 1000, regressions: 0, redTeamResidualHarm: 0.1, receiptsChainVerified: true });
  const check = verifyAutonomyAttestation(good);
  assert.equal(check.valid, true);
  assert.equal(check.meetsBar, true);
  // tamper → invalid
  const tampered = { ...good, answeredFromPlaneRate: 0.99 };
  assert.equal(verifyAutonomyAttestation(tampered).valid, false);
  // valid signature but below bar (has regressions)
  const weak = buildAutonomyAttestation({ issuedAt: now, periodDays: 7, answeredFromPlaneRate: 0.8, totalDecisions: 1000, regressions: 3, redTeamResidualHarm: 0.1, receiptsChainVerified: true });
  const wc = verifyAutonomyAttestation(weak);
  assert.equal(wc.valid, true);
  assert.equal(wc.meetsBar, false);
});

// ---------- time travel ----------
test('time travel: replay a window + attribute drift to the culpable change', () => {
  const mk = (id: string, at: string, amountUsd: number): AdminAction => ({ id, product: 'galop', domain: 'billing', type: 'billing:issue_refund', actor: 's', confidence: 0.97, reversibility: 'reversible', blastRadius: 'single', intent: 'r', amountUsd, at });
  const actions = [mk('a1', '2026-06-10T00:00:00Z', 9), mk('a2', '2026-06-20T00:00:00Z', 9)];
  const win = replayWindow(actions, { fromIso: '2026-06-01T00:00:00Z', toIso: '2026-07-01T00:00:00Z' }, { constitution: fleetAdminConstitution() });
  assert.equal(win.summaries.length, 2);
  assert.ok(win.autonomyRate > 0);

  const base = fleetAdminConstitution();
  const strip = { ...base, rules: base.rules.filter((r) => r.id !== 'allow-refund-small') }; // tightens refunds
  const noop = base;
  const impacts = attributeDrift(actions, { constitution: base }, [
    { label: 'removed-refund-allow', after: { constitution: strip } },
    { label: 'noop', after: { constitution: noop } },
  ]);
  assert.equal(impacts[0]!.label, 'removed-refund-allow'); // the change that flipped decisions ranks first
  assert.ok(impacts[0]!.changed >= 1);
});
