/**
 * Competence–Relevance Matching: the precision filter.
 *
 * Einstein is auto-excluded from a choice-of-law clause (near-zero competence
 * overlap) and auto-recruited onto a derivatives calculation (high overlap on
 * stochastic calculus). Matching, not vibes — and fully auditable.
 */
import { competenceCosine } from './vectors.ts';
import type { IssueSpec, Persona } from './types.ts';

export function relevance(persona: Persona, issue: IssueSpec): number {
  return competenceCosine(persona.competence, issue.requiredCompetence);
}

export interface FilterResult {
  eligible: Persona[];
  excluded: { persona: Persona; relevance: number }[];
  /** relevance score per eligible persona id (kept for the proof record). */
  scores: Record<string, number>;
}

/**
 * Split the roster into eligible vs excluded for this issue. Records every
 * decision so the proof pack can show *who was considered and why*.
 */
export function filterByCompetence(
  roster: Persona[],
  issue: IssueSpec,
  threshold: number,
): FilterResult {
  const eligible: Persona[] = [];
  const excluded: { persona: Persona; relevance: number }[] = [];
  const scores: Record<string, number> = {};
  for (const p of roster) {
    const r = relevance(p, issue);
    // Adversaries/advocates/reviewers are role-gated, not competence-gated:
    // they are always eligible for their stage if they clear a low floor.
    const floor = p.role === 'authority' || p.role === 'discipline' || p.role === 'advisor'
      ? threshold
      : threshold * 0.4;
    if (r >= floor) {
      eligible.push(p);
      scores[p.id] = r;
    } else {
      excluded.push({ persona: p, relevance: r });
    }
  }
  return { eligible, excluded, scores };
}
