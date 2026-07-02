/**
 * Dependency-aware queue — today each app's pending decisions are independent; this models
 * dependencies BETWEEN them so the queue collapses related decisions into one bundled call.
 * "Approving this refund is moot if you're about to terminate the account" — decide the
 * subject's fate once, and the plane fans it out consistently across billing, access, and
 * trust-safety. Pure + zero-dep.
 */
import type { AdminDomain } from './types.ts';

export interface PendingDecision {
  actionId: string;
  subjectId?: string;
  domain: AdminDomain;
  type: string;
  priority: number;
}

/**
 * Precedence: a higher-rank decision SUPERSEDES lower ones on the same subject (deciding it
 * makes the others moot or auto-implied). Account-ending actions dominate everything.
 */
export function precedenceRank(type: string): number {
  const t = type.toLowerCase();
  if (/(terminate|ban|delete)_account/.test(t)) return 100;
  if (/suspend_account/.test(t)) return 80;
  if (/reject_kyc|revoke/.test(t)) return 70;
  if (/dispute_chargeback|exception_credit/.test(t)) return 50;
  if (/issue_refund|retry_payment|grant_role|reset_password/.test(t)) return 30;
  return 10;
}

export interface DecisionBundle {
  subjectId: string;
  primary: PendingDecision;
  subsumed: PendingDecision[];
  reason: string;
}

export interface BundledQueue {
  bundles: DecisionBundle[];
  /** decisions with no subject or no dependencies — handled individually */
  standalone: PendingDecision[];
}

/**
 * Bundle pending decisions by subject: within a subject, the highest-precedence decision
 * becomes the primary and lower ones are subsumed (decided together). Only subjects with
 * ≥2 competing decisions form a bundle.
 */
export function bundleQueue(pending: PendingDecision[]): BundledQueue {
  const bySubject = new Map<string, PendingDecision[]>();
  const standalone: PendingDecision[] = [];
  for (const d of pending) {
    if (!d.subjectId) { standalone.push(d); continue; }
    (bySubject.get(d.subjectId) ?? bySubject.set(d.subjectId, []).get(d.subjectId)!).push(d);
  }

  const bundles: DecisionBundle[] = [];
  for (const [subjectId, arr] of bySubject) {
    if (arr.length < 2) { standalone.push(arr[0]!); continue; }
    const sorted = [...arr].sort((a, b) => precedenceRank(b.type) - precedenceRank(a.type) || b.priority - a.priority);
    const primary = sorted[0]!;
    const subsumed = sorted.slice(1);
    const dominates = precedenceRank(primary.type) > precedenceRank(subsumed[0]!.type);
    bundles.push({
      subjectId,
      primary,
      subsumed,
      reason: dominates
        ? `Deciding '${primary.type}' first resolves ${subsumed.length} lower-precedence decision(s) on this subject`
        : `${arr.length} decisions on the same subject — decide together for consistency`,
    });
  }
  return { bundles: bundles.sort((a, b) => precedenceRank(b.primary.type) - precedenceRank(a.primary.type)), standalone };
}
