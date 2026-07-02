/**
 * Constitution as a market — competing rule-sets (factions) bid, and the twin scores each
 * against real history; the winner is promoted (human-confirmed). The law evolves by
 * selection pressure instead of anyone hand-authoring it. A "tight" faction and a "lean"
 * faction each propose the constitution; fitness rewards correctly-automated decisions and
 * heavily penalizes regressions. Pure + zero-dep.
 */
import type { Constitution, ConstitutionRule } from '../governance/constitution.ts';
import { rule } from '../governance/constitution.ts';
import { fleetAdminConstitution } from './constitution.ts';
import { governFleetAction } from './govern.ts';
import type { AdminAction } from './types.ts';
import type { ResolvedCase } from './precedent.ts';

export interface RuleFaction {
  name: string;
  constitution: Constitution;
}

export interface FactionScore {
  name: string;
  correctAutos: number; // auto-ran an action the human clean-approved
  regressions: number; // auto-ran an action the human edited/rejected (heavy penalty)
  unnecessaryEscalations: number; // escalated an action the human clean-approved
  fitness: number;
}

const REGRESSION_PENALTY = 5;
const ESCALATION_PENALTY = 0.2;

/** Score a faction by replaying history under its constitution vs. the human outcomes. */
export function scoreFaction(
  faction: RuleFaction,
  history: AdminAction[],
  outcomes: Record<string, ResolvedCase['outcome']>,
): FactionScore {
  let correctAutos = 0;
  let regressions = 0;
  let unnecessaryEscalations = 0;
  for (const a of history) {
    const outcome = outcomes[a.id];
    if (!outcome) continue;
    const v = governFleetAction({ action: a, constitution: faction.constitution });
    const auto = v.decision === 'allow' && v.tier === 'auto';
    if (auto && outcome === 'approve') correctAutos++;
    else if (auto && outcome !== 'approve') regressions++;
    else if (!auto && outcome === 'approve') unnecessaryEscalations++;
  }
  const fitness = correctAutos - REGRESSION_PENALTY * regressions - ESCALATION_PENALTY * unnecessaryEscalations;
  return { name: faction.name, correctAutos, regressions, unnecessaryEscalations, fitness: Math.round(fitness * 100) / 100 };
}

/** Three built-in factions from the base fleet law: tighter, balanced, leaner. */
export function factionVariants(base: Constitution = fleetAdminConstitution()): RuleFaction[] {
  // TIGHT: strip the routine allows so more decisions escalate.
  const tight: Constitution = { ...base, version: base.version, rules: base.rules.filter((r) => !r.id.startsWith('allow-')) };
  // LEAN: add a few extra safe allows (more auto).
  const leanExtras: ConstitutionRule[] = [
    rule.allowUnder('allow-verify-identity', 'users_access:verify_identity', Number.MAX_SAFE_INTEGER, 40),
    rule.allowUnder('allow-flag-review', 'trust_safety:flag_for_review', Number.MAX_SAFE_INTEGER, 40),
    rule.allowUnder('allow-restart-worker', 'infra:restart_worker', Number.MAX_SAFE_INTEGER, 40),
  ];
  const lean: Constitution = { ...base, rules: [...base.rules, ...leanExtras] };
  return [
    { name: 'tight', constitution: tight },
    { name: 'balanced', constitution: base },
    { name: 'lean', constitution: lean },
  ];
}

export interface MarketResult {
  ranked: FactionScore[];
  winner: string;
}

/** Run the market: score every faction on history, rank by fitness, declare a winner. */
export function runRuleMarket(
  factions: RuleFaction[],
  history: AdminAction[],
  outcomes: Record<string, ResolvedCase['outcome']>,
): MarketResult {
  const ranked = factions.map((f) => scoreFaction(f, history, outcomes)).sort((a, b) => b.fitness - a.fitness);
  return { ranked, winner: ranked[0]?.name ?? 'none' };
}
