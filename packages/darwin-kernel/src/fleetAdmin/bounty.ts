/**
 * Adversarial bounty market — turn red-teaming into an incentivized, self-funding market.
 * Finders (agents or humans) submit action shapes they claim will AUTO-run above the harm
 * threshold; each submission is validated against the REAL gate, and an accepted finding pays a
 * bounty AND auto-drafts a constitution amendment that closes the gap. Security hardening
 * becomes a market, not a fixed sweep. Pure + zero-dep.
 */
import { fleetAdminConstitution } from './constitution.ts';
import { DEFAULT_DOMAIN_POLICIES, type DomainAutonomyPolicy } from './autonomy.ts';
import { governFleetAction } from './govern.ts';
import type { AdminAction, AdminDomain, Reversibility, BlastRadius } from './types.ts';
import type { ProposedAmendment } from './constitutionLearner.ts';
import { fleetHarmScore as harm } from './shared.ts';

export interface GapSubmission {
  id: string;
  finder: string;
  domain: AdminDomain;
  actionType: string;
  amountUsd?: number;
  reversibility: Reversibility;
  blastRadius: BlastRadius;
  confidence: number;
}

export interface BountyConfig {
  harmThreshold: number;
  /** payout = base + perHarm × harmScore for an accepted finding */
  baseUsd: number;
  perHarmUsd: number;
}
export const DEFAULT_BOUNTY_CONFIG: BountyConfig = { harmThreshold: 0.3, baseUsd: 50, perHarmUsd: 500 };

export interface BountyFinding {
  submissionId: string;
  finder: string;
  accepted: boolean;
  wouldAutoRun: boolean;
  harmScore: number;
  payoutUsd: number;
  /** the amendment drafted to close an accepted gap */
  amendment?: ProposedAmendment;
  reason: string;
}

/** Validate a single submission against the live gate. Accepted only if it truly auto-runs + is harmful. */
export function evaluateSubmission(
  s: GapSubmission,
  policies: Record<AdminDomain, DomainAutonomyPolicy> = DEFAULT_DOMAIN_POLICIES,
  cfg: BountyConfig = DEFAULT_BOUNTY_CONFIG,
): BountyFinding {
  const action: AdminAction = {
    id: `bounty_${s.id}`, product: 'orchestrator', domain: s.domain, type: s.actionType, actor: s.finder,
    confidence: s.confidence, reversibility: s.reversibility, blastRadius: s.blastRadius, intent: 'bounty submission',
    amountUsd: s.amountUsd, at: '2026-07-01T00:00:00.000Z',
  };
  const v = governFleetAction({ action, constitution: fleetAdminConstitution(), policies });
  const wouldAutoRun = v.decision === 'allow' && v.tier === 'auto';
  const harmScore = harm(s);
  const accepted = wouldAutoRun && harmScore >= cfg.harmThreshold;
  const payoutUsd = accepted ? Math.round(cfg.baseUsd + cfg.perHarmUsd * harmScore) : 0;

  const amendment: ProposedAmendment | undefined = accepted
    ? { domain: s.domain, actionType: s.actionType, kind: 'always_escalate', ruleText: `Always escalate '${s.actionType}' — bounty-found auto-run gap (harm ${harmScore})`, support: 1, confidence: harmScore }
    : undefined;

  return {
    submissionId: s.id, finder: s.finder, accepted, wouldAutoRun, harmScore, payoutUsd, amendment,
    reason: accepted ? `accepted: auto-runs at harm ${harmScore}` : wouldAutoRun ? `auto-runs but harm ${harmScore} < ${cfg.harmThreshold}` : `gated (${v.decision}/${v.tier}) — not a gap`,
  };
}

export interface BountyRound {
  findings: BountyFinding[];
  accepted: BountyFinding[];
  totalPayoutUsd: number;
  leaderboard: { finder: string; findings: number; payoutUsd: number }[];
  amendments: ProposedAmendment[];
}

/** Run a whole submission batch → accepted findings + payouts + drafted amendments + leaderboard. */
export function runBountyRound(
  submissions: GapSubmission[],
  policies: Record<AdminDomain, DomainAutonomyPolicy> = DEFAULT_DOMAIN_POLICIES,
  cfg: BountyConfig = DEFAULT_BOUNTY_CONFIG,
): BountyRound {
  const findings = submissions.map((s) => evaluateSubmission(s, policies, cfg));
  const accepted = findings.filter((f) => f.accepted);
  const board = new Map<string, { findings: number; payoutUsd: number }>();
  for (const f of accepted) {
    const e = board.get(f.finder) ?? { findings: 0, payoutUsd: 0 };
    e.findings += 1; e.payoutUsd += f.payoutUsd; board.set(f.finder, e);
  }
  return {
    findings,
    accepted,
    totalPayoutUsd: accepted.reduce((s, f) => s + f.payoutUsd, 0),
    leaderboard: [...board.entries()].map(([finder, v]) => ({ finder, ...v })).sort((a, b) => b.payoutUsd - a.payoutUsd),
    amendments: accepted.map((f) => f.amendment!).filter(Boolean),
  };
}
