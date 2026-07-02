import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  replayPromotion,
  simulateBlast,
  promotionDossier,
  propagateFix,
  correlateEvents,
  proposeAmendments,
  runRedTeam,
  buildApproverProfile,
  predictDecision,
  prefillEdit,
  orderQueueForApprover,
  DEFAULT_DOMAIN_POLICIES,
  AdminSeverity,
  type ResolvedCase,
  type ExposureRecord,
  type LedgerEntry,
  type AdminAction,
  type AdminEvent,
  type ApproverDecisionRecord,
} from '../src/fleetAdmin/index.ts';

const now = '2026-07-01T00:00:00.000Z';
function rc(outcome: ResolvedCase['outcome'], amountUsd = 9, over: Partial<ResolvedCase> = {}): ResolvedCase {
  return { domain: 'billing', type: 'billing:issue_refund', amountUsd, reversibility: 'reversible', blastRadius: 'single', outcome, at: now, ...over };
}

// ---------- counterfactual replay ----------
test('replay: clean history is safe to promote; dirty history holds', () => {
  const clean = replayPromotion({ domain: 'billing', actionType: 'billing:issue_refund', proposedTier: 'auto' }, Array.from({ length: 30 }, () => rc('approve')));
  assert.equal(clean.recommendation, 'safe_to_promote');
  assert.equal(clean.falsePositiveRate, 0);

  const dirty = replayPromotion({ domain: 'billing', actionType: 'billing:issue_refund', proposedTier: 'auto' },
    [...Array.from({ length: 25 }, () => rc('approve')), ...Array.from({ length: 5 }, () => rc('reject'))]);
  assert.equal(dirty.recommendation, 'hold');
  assert.ok(dirty.falsePositiveRate > 0.02);
  assert.equal(dirty.divergences, 5);
});
test('replay: insufficient history is flagged', () => {
  assert.equal(replayPromotion({ domain: 'billing', actionType: 'x', proposedTier: 'auto' }, [rc('approve')]).recommendation, 'insufficient_history');
});

// ---------- blast simulator ----------
test('blast: concentrated exposure in one app is flagged', () => {
  const recs: ExposureRecord[] = [
    { product: 'galop', amountUsd: 900, at: '2026-06-01T00:00:00Z' },
    { product: 'galop', amountUsd: 900, at: '2026-06-02T00:00:00Z' },
    { product: 'pareto', amountUsd: 50, at: '2026-06-02T00:00:00Z' },
  ];
  const b = simulateBlast({ domain: 'billing', actionType: 'billing:issue_refund' }, recs);
  assert.equal(b.appsAffected, 2);
  assert.equal(b.recommendation, 'concentrated_blast');
  assert.ok(b.concentration >= 0.75);
});
test('blast: high daily exposure is flagged high', () => {
  const recs: ExposureRecord[] = Array.from({ length: 5 }, (_, i) => ({ product: `app${i}`, amountUsd: 6000, at: '2026-06-01T00:00:00Z' }));
  assert.equal(simulateBlast({ domain: 'billing', actionType: 't' }, recs).recommendation, 'high_blast');
});

// ---------- dossier (value + safety + blast) ----------
test('dossier recommends only when valuable, safe, and low-blast', () => {
  const entry: LedgerEntry = { actionType: 'billing:issue_refund', domain: 'billing', streak: 25, total: 25, cleanApprovals: 25, edits: 0, rejections: 0, updatedAt: now };
  const history = Array.from({ length: 30 }, () => rc('approve'));
  const exposure: ExposureRecord[] = [{ product: 'galop', amountUsd: 20, at: '2026-06-01T00:00:00Z' }, { product: 'pareto', amountUsd: 25, at: '2026-06-02T00:00:00Z' }];
  const d = promotionDossier(entry, history, exposure, (dm) => DEFAULT_DOMAIN_POLICIES[dm].ceiling)!;
  assert.equal(d.verdict, 'recommend');

  const dirty = promotionDossier(entry, [...Array.from({ length: 20 }, () => rc('approve')), ...Array.from({ length: 10 }, () => rc('reject'))], exposure, (dm) => DEFAULT_DOMAIN_POLICIES[dm].ceiling)!;
  assert.equal(dirty.verdict, 'hold');
});

// ---------- fix propagation ----------
test('propagates a fix to peer apps sharing the root-cause signal', () => {
  const base = Date.parse(now);
  const events: AdminEvent[] = [
    { id: 'e1', product: 'apparently', domain: 'infra', category: 'error_spike', severity: 60, title: 'db', summary: '', at: new Date(base).toISOString(), details: { provider: 'supabase-east' } },
    { id: 'e2', product: 'pareto', domain: 'infra', category: 'error_spike', severity: 60, title: 'db', summary: '', at: new Date(base + 60000).toISOString(), details: { provider: 'supabase-east' } },
    { id: 'e3', product: 'galop', domain: 'infra', category: 'outage', severity: 100, title: 'x', summary: '', at: new Date(base + 120000).toISOString(), details: { provider: 'supabase-east' } },
  ];
  const incident = correlateEvents(events)[0]!;
  const fixing: AdminAction = { id: 'fix1', product: 'apparently', domain: 'infra', type: 'infra:rollback_deploy', actor: 'infra-swarm', eventId: 'e1', confidence: 0.9, reversibility: 'reversible', blastRadius: 'small', intent: 'Roll back the bad deploy', at: now };
  const proposals = propagateFix(incident, fixing, events);
  // e1 is the origin; e2 and e3 share the signal → 2 propagated proposals
  assert.equal(proposals.length, 2);
  assert.ok(proposals.every((p) => p.action.type === 'infra:rollback_deploy'));
  assert.ok(proposals.some((p) => p.action.product === 'pareto'));
});

// ---------- self-rewriting constitution ----------
test('mines rejections into amendment proposals', () => {
  // A type rejected 80% of the time → always_escalate
  const history: ResolvedCase[] = [
    ...Array.from({ length: 8 }, () => rc('reject', 0, { type: 'users_access:grant_admin_role', domain: 'users_access' as const })),
    ...Array.from({ length: 2 }, () => rc('approve', 0, { type: 'users_access:grant_admin_role', domain: 'users_access' as const })),
  ];
  const proposals = proposeAmendments(history);
  assert.ok(proposals.length >= 1);
  assert.equal(proposals[0]!.kind, 'always_escalate');
  assert.equal(proposals[0]!.actionType, 'users_access:grant_admin_role');
});
test('mines an amount cap when rejections cluster above approvals', () => {
  const history: ResolvedCase[] = [
    ...Array.from({ length: 5 }, () => rc('approve', 20)),
    ...Array.from({ length: 5 }, () => rc('reject', 500)),
  ];
  const capped = proposeAmendments(history).find((p) => p.kind === 'amount_cap');
  assert.ok(capped);
  assert.equal(capped!.thresholdUsd, 20);
});

// ---------- red team ----------
test('red team finds no auto-run gaps under the default ceilings', () => {
  const { findings, gaps } = runRedTeam();
  assert.ok(findings.length > 0);
  // The default policies should not auto-run harmful probes (money over cap, fleet blast, irreversible).
  assert.equal(gaps.length, 0);
});
test('red team DOES find a gap if a domain ceiling is recklessly loosened', () => {
  const reckless = structuredClone(DEFAULT_DOMAIN_POLICIES);
  reckless.billing.autoMaxUsd = 1_000_000;
  reckless.billing.autoReversibility = ['reversible', 'hard_to_reverse', 'irreversible'];
  reckless.billing.autoMaxBlast = 'fleet';
  const { gaps } = runRedTeam(reckless);
  assert.ok(gaps.length > 0);
});

// ---------- approver model ----------
test('learns preferences, predicts, prefills, and orders the queue', () => {
  const records: ApproverDecisionRecord[] = [
    ...Array.from({ length: 8 }, () => ({ domain: 'billing' as const, actionType: 'billing:issue_refund', outcome: 'approve' as const, at: '2026-06-01T09:00:00Z' })),
    ...Array.from({ length: 5 }, () => ({ domain: 'trust_safety' as const, actionType: 'trust_safety:terminate_account', outcome: 'reject' as const, at: '2026-06-01T14:00:00Z' })),
    ...Array.from({ length: 3 }, () => ({ domain: 'billing' as const, actionType: 'billing:issue_exception_credit', outcome: 'modify' as const, at: '2026-06-01T10:00:00Z', modifiedParams: { amount: 100 } })),
  ];
  const profile = buildApproverProfile(records);
  assert.equal(predictDecision(profile, 'billing', 'billing:issue_refund').likely, 'approve');
  assert.equal(predictDecision(profile, 'trust_safety', 'trust_safety:terminate_account').likely, 'reject');
  assert.ok(profile.scrutinizedDomains.includes('trust_safety'));
  assert.deepEqual(prefillEdit(profile, 'billing', 'billing:issue_exception_credit'), { amount: 100 });

  const ordered = orderQueueForApprover(profile, [
    { domain: 'billing', actionType: 'billing:issue_refund', priority: 20 }, // rubber-stamp → low attention
    { domain: 'trust_safety', actionType: 'trust_safety:terminate_account', priority: 40 }, // scrutinized → high
  ]);
  assert.equal(ordered[0]!.domain, 'trust_safety');
});
