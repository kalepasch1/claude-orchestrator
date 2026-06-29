/**
 * The Conclave Selector — panel optimization.
 *
 * Greedy facility-location (submodular) coverage of the predicted-argument space,
 * traded off against quality (authority × reliability) via `diversityWeight`. Adds
 * minds while marginal coverage gain stays above `infoGainStop`; the gain of the
 * first REJECTED candidate becomes the certificate's marginal-value bound (ε) — the
 * formal "no excluded mind would have moved this" number. Reserves a heretic quota
 * for high-option-value outliers and guarantees stance opposition.
 */
import { centroid, distance } from './vectors.ts';
import type { CadeOptions, Persona, PersonaPosition } from './types.ts';

export interface Candidate {
  persona: Persona;
  position: PersonaPosition;
}

export interface PanelSelection {
  seated: Candidate[];
  /** ε: marginal contribution of the best mind we left out. */
  marginalValueBound: number;
  /** Adding further minds stopped raising coverage above the stop threshold. */
  saturated: boolean;
  hereticsSeated: number;
}

function quality(p: Persona): number {
  return (p.authority + p.reliability) / 2;
}

/** Coverage gain of `c` given the already-seated set: distance to nearest seated. */
function marginalCoverage(c: Candidate, seated: Candidate[]): number {
  if (seated.length === 0) return 1;
  let min = Infinity;
  for (const s of seated) {
    const d = distance(c.position.embedding, s.position.embedding);
    if (d < min) min = d;
  }
  // distances are roughly [0, ~1.4] for unit vectors; clamp to [0,1].
  return Math.min(1, min / Math.SQRT2);
}

function score(c: Candidate, seated: Candidate[], diversityWeight: number): number {
  return diversityWeight * marginalCoverage(c, seated) + (1 - diversityWeight) * quality(c.persona);
}

export function selectPanel(
  candidates: Candidate[],
  maxSeats: number,
  opts: Required<Pick<CadeOptions, 'diversityWeight' | 'infoGainStop' | 'hereticQuota'>>,
): PanelSelection {
  const pool = [...candidates];
  const seated: Candidate[] = [];
  let saturated = false;
  let marginalValueBound = 0;

  // Seed with the highest-quality mind.
  pool.sort((a, b) => quality(b.persona) - quality(a.persona));
  const first = pool.shift();
  if (first) seated.push(first);

  while (seated.length < maxSeats && pool.length > 0) {
    let bestIdx = -1;
    let bestScore = -Infinity;
    for (let i = 0; i < pool.length; i++) {
      const cand = pool[i];
      if (!cand) continue;
      const s = score(cand, seated, opts.diversityWeight);
      if (s > bestScore) {
        bestScore = s;
        bestIdx = i;
      }
    }
    if (bestIdx < 0) break;
    const pick = pool[bestIdx];
    if (!pick) break;
    const gain = marginalCoverage(pick, seated);
    if (gain < opts.infoGainStop) {
      // The best remaining mind adds negligible coverage → stop. Record ε.
      marginalValueBound = gain;
      saturated = true;
      break;
    }
    seated.push(pick);
    pool.splice(bestIdx, 1);
  }

  // If we never hit the stop threshold, ε is the best leftover's coverage gain.
  if (!saturated && pool.length > 0) {
    let best = 0;
    for (const c of pool) best = Math.max(best, marginalCoverage(c, seated));
    marginalValueBound = best;
  }

  // Productive-heretic quota: ensure outlier views (or exploration-tagged minds).
  const quotaNeeded = Math.ceil(opts.hereticQuota * Math.max(1, seated.length));
  let hereticsSeated = seated.filter((c) => c.persona.exploration).length;
  if (hereticsSeated < quotaNeeded && pool.length > 0 && seated.length < maxSeats) {
    const seatedEmb = seated.map((c) => c.position.embedding);
    const ctr = centroid(seatedEmb);
    // Highest option value ≈ farthest from the seated centroid.
    pool.sort((a, b) => distance(b.position.embedding, ctr) - distance(a.position.embedding, ctr));
    while (hereticsSeated < quotaNeeded && pool.length > 0 && seated.length < maxSeats) {
      const h = pool.shift();
      if (!h) break;
      seated.push(h);
      hereticsSeated++;
    }
  }

  return { seated, marginalValueBound, saturated, hereticsSeated };
}

/**
 * Adversarial-completeness guarantee (selection-time approximation): if every
 * seated stance shares one sign, force-seat the most opposed available candidate so
 * no position can win by absence of opposition. Final completeness is re-checked
 * after factions form.
 */
export function ensureOpposition(
  seated: Candidate[],
  pool: Candidate[],
): { seated: Candidate[]; added?: Candidate } {
  if (seated.length === 0 || pool.length === 0) return { seated };
  const signs = new Set(seated.map((c) => Math.sign(c.position.stance)));
  if (signs.size > 1) return { seated }; // opposition already present
  const dominant = Math.sign(seated[0]?.position.stance ?? 0);
  let opp: Candidate | undefined;
  let bestOpp = -Infinity;
  for (const c of pool) {
    const opposition = -dominant * c.position.stance; // larger = more opposed
    if (opposition > bestOpp) {
      bestOpp = opposition;
      opp = c;
    }
  }
  if (opp && bestOpp > 0) return { seated: [...seated, opp], added: opp };
  return { seated };
}
