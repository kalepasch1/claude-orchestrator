/**
 * The self-rewriting constitution — every rejection is a signal the law is missing a
 * rule. Mine the resolved-decision log for patterns Bear consistently rejects and DRAFT
 * the constitution amendment as a materiality-gated proposal. The law tightens itself
 * from your decisions; because it's the shared Darwin Kernel constitution, an accepted
 * amendment propagates to every app at once. Pure + zero-dep. Proposals only — never
 * self-applied.
 */
import type { AdminDomain } from './types.ts';
import type { ResolvedCase } from './precedent.ts';

export interface ProposedAmendment {
  domain: AdminDomain;
  actionType: string;
  kind: 'always_escalate' | 'deny' | 'amount_cap';
  /** the rule, in plain English, for the audit trail + your review */
  ruleText: string;
  /** amount threshold for an 'amount_cap' proposal */
  thresholdUsd?: number;
  /** how many rejections back this proposal */
  support: number;
  /** rejection rate among matching cases, 0..1 */
  confidence: number;
}

export interface LearnerConfig {
  minSample: number;
  /** rejection rate at/above which a type should always escalate */
  escalateRate: number;
  /** rejection rate at/above which a type should be denied outright */
  denyRate: number;
}

export const DEFAULT_LEARNER_CONFIG: LearnerConfig = { minSample: 8, escalateRate: 0.7, denyRate: 0.95 };

/** Mine resolved history for amendment proposals. */
export function proposeAmendments(
  history: ResolvedCase[],
  cfg: LearnerConfig = DEFAULT_LEARNER_CONFIG,
): ProposedAmendment[] {
  const groups = new Map<string, ResolvedCase[]>();
  for (const c of history) {
    const k = `${c.domain}::${c.type}`;
    const arr = groups.get(k) ?? [];
    arr.push(c);
    groups.set(k, arr);
  }

  const out: ProposedAmendment[] = [];
  for (const [, cases] of groups) {
    if (cases.length < cfg.minSample) continue;
    const domain = cases[0]!.domain;
    const actionType = cases[0]!.type;
    const rejects = cases.filter((c) => c.outcome === 'reject');
    const rejRate = rejects.length / cases.length;

    // Type-level: consistently rejected → deny or always-escalate.
    if (rejRate >= cfg.denyRate) {
      out.push({ domain, actionType, kind: 'deny', ruleText: `Deny '${actionType}' — rejected ${Math.round(rejRate * 100)}% of the time`, support: rejects.length, confidence: Math.round(rejRate * 100) / 100 });
      continue;
    }
    if (rejRate >= cfg.escalateRate) {
      out.push({ domain, actionType, kind: 'always_escalate', ruleText: `Always escalate '${actionType}' — rejected ${Math.round(rejRate * 100)}% of the time`, support: rejects.length, confidence: Math.round(rejRate * 100) / 100 });
      continue;
    }

    // Amount-level: rejects cluster above a threshold that approvals stay below.
    const approves = cases.filter((c) => c.outcome === 'approve' && (c.amountUsd ?? 0) > 0);
    const rejectsWithAmt = rejects.filter((c) => (c.amountUsd ?? 0) > 0);
    if (rejectsWithAmt.length >= Math.max(3, cfg.minSample / 2) && approves.length >= 3) {
      const maxApproved = Math.max(...approves.map((c) => c.amountUsd ?? 0));
      const minRejected = Math.min(...rejectsWithAmt.map((c) => c.amountUsd ?? 0));
      // Clean separation: everything above maxApproved was rejected.
      if (minRejected > maxApproved) {
        out.push({
          domain, actionType, kind: 'amount_cap', thresholdUsd: maxApproved,
          ruleText: `Escalate '${actionType}' above $${maxApproved} — approvals stayed ≤ $${maxApproved}, rejections began at $${minRejected}`,
          support: rejectsWithAmt.length, confidence: Math.round((rejectsWithAmt.length / (rejectsWithAmt.length + approves.length)) * 100) / 100,
        });
      }
    }
  }
  return out.sort((a, b) => b.support - a.support);
}
