/**
 * Digital-twin dry-run — before ANY change to the plane itself (a new ceiling, a new
 * constitution, an accepted amendment), replay the change against the real historical
 * action stream and report exactly which decisions would flip, with zero side effects.
 * Every policy change becomes a measured experiment: "this would have changed 43 calls
 * last week — here are the 5 you'd disagree with." Pure + zero-dep.
 */
import type { Constitution } from '../governance/constitution.ts';
import { governFleetAction } from './govern.ts';
import { DEFAULT_DOMAIN_POLICIES, type DomainAutonomyPolicy } from './autonomy.ts';
import { fleetAdminConstitution } from './constitution.ts';
import type { AdminAction, AdminDomain, AutonomyTier } from './types.ts';
import type { Decision } from '../types.ts';
import type { ResolvedCase } from './precedent.ts';

export interface PlaneConfigSnapshot {
  constitution?: Constitution;
  policies?: Record<AdminDomain, DomainAutonomyPolicy>;
}

export interface DecisionDiff {
  actionId: string;
  product: string;
  domain: AdminDomain;
  type: string;
  before: { decision: Decision; tier: AutonomyTier };
  after: { decision: Decision; tier: AutonomyTier };
  /** the human's actual outcome for this action, if known — flags real disagreements */
  humanOutcome?: 'approve' | 'modify' | 'reject';
  /** true when the NEW config would auto-run something the human did NOT clean-approve */
  wouldRegress: boolean;
}

export interface TwinResult {
  sampleSize: number;
  changed: number;
  /** of the changed decisions, how many the new config gets MORE autonomous */
  loosened: number;
  tightened: number;
  /** changes that would auto-run something a human previously edited/rejected */
  regressions: number;
  diffs: DecisionDiff[];
  summary: string;
}

const TIER_RANK: Record<AutonomyTier, number> = { human: 0, co_pilot: 1, auto: 2 };

/**
 * Replay `actions` under the current config vs. a candidate config and diff. Optionally
 * pass the actions' human outcomes (by id) to flag regressions — changes that would let
 * the plane auto-run something you previously rejected/edited.
 */
export function dryRunChange(params: {
  actions: AdminAction[];
  after: PlaneConfigSnapshot;
  before?: PlaneConfigSnapshot;
  outcomes?: Record<string, ResolvedCase['outcome']>;
}): TwinResult {
  const before = params.before ?? {};
  const beforeConst = before.constitution ?? fleetAdminConstitution();
  const beforePol = before.policies ?? DEFAULT_DOMAIN_POLICIES;
  const afterConst = params.after.constitution ?? fleetAdminConstitution();
  const afterPol = params.after.policies ?? DEFAULT_DOMAIN_POLICIES;

  const diffs: DecisionDiff[] = [];
  let loosened = 0;
  let tightened = 0;
  let regressions = 0;

  for (const a of params.actions) {
    const b = governFleetAction({ action: a, constitution: beforeConst, policies: beforePol });
    const af = governFleetAction({ action: a, constitution: afterConst, policies: afterPol });
    if (b.decision === af.decision && b.tier === af.tier) continue;

    const outcome = params.outcomes?.[a.id];
    const moreAuto = TIER_RANK[af.tier] > TIER_RANK[b.tier];
    if (moreAuto) loosened++;
    else tightened++;
    const wouldRegress = af.decision === 'allow' && af.tier === 'auto' && !!outcome && outcome !== 'approve';
    if (wouldRegress) regressions++;

    diffs.push({
      actionId: a.id, product: a.product, domain: a.domain, type: a.type,
      before: { decision: b.decision, tier: b.tier },
      after: { decision: af.decision, tier: af.tier },
      humanOutcome: outcome, wouldRegress,
    });
  }

  return {
    sampleSize: params.actions.length,
    changed: diffs.length,
    loosened, tightened, regressions,
    diffs,
    summary:
      `${diffs.length}/${params.actions.length} decisions would change ` +
      `(${loosened} looser, ${tightened} tighter, ${regressions} regressions). ` +
      (regressions === 0 ? 'No regressions against known human outcomes.' : `⚠ ${regressions} would auto-run a previously non-approved action.`),
  };
}
