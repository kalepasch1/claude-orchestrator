/**
 * The recursive CADE orchestrator.
 *
 * runDetermination() runs one contestable unit through:
 *   relevance gate → cheap standing-roster pass → (recursive Expert Councils on
 *   sub-questions) → conclave deep-panel selection → blinded debate rounds with
 *   emergent factions → convergence test → adversarial red-team challenge (iterate
 *   on material hits) → optimality certificate + signed proof pack.
 *
 * Materiality picks the cost tier (panel size, rounds, recursion depth). The engine
 * is pure orchestration; all model calls go through the injected Invoker.
 */
import {
  DEFAULT_OPTIONS,
  type CadeOptions,
  type Determination,
  type Embedder,
  type Faction,
  type Invoker,
  type IssueSpec,
  type Persona,
  type PersonaPosition,
  type ProofPack,
  type RedTeamHit,
  type ReviewerModel,
} from './types.ts';
import { filterByCompetence } from './competence.ts';
import { selectPanel, ensureOpposition, type Candidate } from './conclave.ts';
import {
  clusterFactions,
  factionDistribution,
  hasConverged,
  jackknifeRobust,
} from './factions.ts';
import { buildCertificate, buildProofPack } from './certificate.ts';
import { summarize } from './vectors.ts';

interface Tier {
  maxSeats: number;
  maxRounds: number;
  cheapCap: number;
}

function tierFor(materiality: number, opts: Required<Omit<CadeOptions, 'sign' | 'now'>>): Tier {
  if (materiality < 0.33) return { maxSeats: 5, maxRounds: 1, cheapCap: 40 };
  if (materiality < 0.66) return { maxSeats: 12, maxRounds: Math.min(3, opts.maxRounds), cheapCap: 200 };
  return { maxSeats: 24, maxRounds: opts.maxRounds, cheapCap: 1000 };
}

export interface RunDeps {
  invoker: Invoker;
  embedder: Embedder;
}

export async function runDetermination(
  issue: IssueSpec,
  roster: Persona[],
  deps: RunDeps,
  options: CadeOptions = {},
  depth = 0,
): Promise<Determination> {
  const opts = { ...DEFAULT_OPTIONS, ...stripUndef(options) };
  const now = options.now ?? (() => new Date().toISOString());
  const tier = tierFor(issue.materiality, opts);

  // Distribution summary (finance/loan/insurance) — what the panel argues over.
  if (issue.distribution && issue.distribution.p50 === undefined) {
    Object.assign(issue.distribution, summarize(issue.distribution.samples));
  }

  // 1) relevance gate
  const { eligible, excluded } = filterByCompetence(roster, issue, opts.relevanceThreshold);
  const substantive = eligible.filter((p) => p.role === 'authority' || p.role === 'discipline');
  const reliabilityOf = (id: string) => roster.find((p) => p.id === id)?.reliability ?? 0.5;

  // 2) cheap standing-roster pass (Tier A) — everyone relevant opines, cheaply.
  const cheapPool = substantive.slice(0, tier.cheapCap);
  const cheapPositions = await invokeAll(cheapPool, issue, 'cheap', deps);

  // 3) recursive Expert Councils on surfaced technical sub-questions.
  const councils: ProofPack[] = [];
  if (depth < opts.maxDepth) {
    const subs = dedupeIssues(cheapPositions.flatMap((p) => p.subQuestions ?? []));
    for (const sub of subs.slice(0, 3)) {
      const advisorRoster = roster.filter((p) => p.role === 'advisor' || p.role === 'discipline');
      const sd = await runDetermination(sub, advisorRoster, deps, options, depth + 1);
      councils.push(sd.proof);
    }
  }

  // 4) conclave: select the deep panel from the disagreement frontier.
  let candidates: Candidate[] = cheapPositions
    .map((pos) => {
      const persona = cheapPool.find((p) => p.id === pos.personaId);
      return persona ? { persona, position: pos } : undefined;
    })
    .filter((c): c is Candidate => !!c);

  const sel = selectPanel(candidates, tier.maxSeats, {
    diversityWeight: opts.diversityWeight,
    infoGainStop: opts.infoGainStop,
    hereticQuota: opts.hereticQuota,
  });
  const remaining = candidates.filter((c) => !sel.seated.includes(c));
  const opp = ensureOpposition(sel.seated, remaining);
  const seated = opp.seated;

  // 5) blinded debate rounds → emergent factions → convergence.
  let positions: PersonaPosition[] = seated.map((c) => c.position);
  let factions: Faction[] = clusterFactions(positions, reliabilityOf);
  let prevDist = factionDistribution(factions);
  let rounds = 1;
  let converged = positions.length <= 2;
  for (let r = 2; r <= tier.maxRounds && !converged; r++) {
    const counters = factions.slice(1).map((f) => f.positionSummary);
    positions = await invokeAll(
      seated.map((c) => c.persona),
      issue,
      'deep',
      deps,
      { counterArguments: counters, round: r },
    );
    factions = clusterFactions(positions, reliabilityOf);
    const dist = factionDistribution(factions);
    rounds = r;
    converged = hasConverged(prevDist, dist, opts.convergenceEpsilon);
    prevDist = dist;
  }

  // 6) adversarial red team — symmetric firepower, paid to break it.
  const adversaries = eligible.filter((p) => p.role === 'adversary');
  const lead = factions[0];
  const redTeam = await runRedTeam(adversaries, issue, lead, deps);
  const unrebuttedFatal = redTeam.some((h) => h.severity === 'fatal' && !h.rebutted);
  // One revision pass if a fatal hit landed and we have round budget.
  if (unrebuttedFatal && rounds < tier.maxRounds + 1) {
    const counters = redTeam.filter((h) => !h.rebutted).map((h) => h.claim);
    positions = await invokeAll(
      seated.map((c) => c.persona),
      issue,
      'deep',
      deps,
      { counterArguments: counters, round: rounds + 1 },
    );
    factions = clusterFactions(positions, reliabilityOf);
    rounds += 1;
  }

  // 7) Tribunal Model (if reviewer personas present).
  const reviewerModel = buildReviewerModel(eligible.filter((p) => p.role === 'reviewer'), options);

  // 8) certificate + proof.
  const finalLead = factions[0];
  const totalSupport = factions.reduce((s, f) => s + f.support, 0) || 1;
  const leadSupport = (finalLead?.support ?? 0) / totalSupport;
  const jk = jackknifeRobust(positions, reliabilityOf);
  const adversariallyComplete =
    (new Set(positions.map((p) => Math.sign(p.stance))).size > 1 || !!opp.added) &&
    !redTeam.some((h) => h.severity === 'fatal' && !h.rebutted);

  const certificate = buildCertificate({
    rosterClass: issue.rosterClass,
    rosterComplete: !!issue.rosterClass,
    consideredCount: substantive.length,
    seatedCount: seated.length,
    marginalValueBound: sel.marginalValueBound,
    saturated: sel.saturated,
    adversariallyComplete,
    leadSupport,
    jackknifeRobust: jk.robust,
  });

  const proof = buildProofPack(
    {
      issue,
      consideredPersonaIds: substantive.map((p) => p.id),
      excludedPersonaIds: excluded.map((e) => e.persona.id),
      seatedPersonaIds: seated.map((c) => c.persona.id),
      rounds,
      factions,
      redTeam,
      certificate,
      councils: councils.length ? councils : undefined,
      distribution: issue.distribution,
      createdAt: now(),
    },
    options.sign ?? false,
  );
  // reviewerModel is recorded alongside (kept out of the digest input above so it
  // does not affect the substance hash — substance is reviewer-blind by design).
  proof.record.reviewerModel = reviewerModel;

  const unsettled = !converged && tier.maxRounds > 1;
  const numeric = numericAnswer(factions, positions);

  return {
    issueId: issue.id,
    position: finalLead?.positionSummary ?? 'no position',
    value: numeric,
    confidence: certificate.confidence,
    dissent: factions.slice(1),
    factions,
    certificate,
    proof,
    unsettled,
  };
}

// ---------- helpers ----------

async function invokeAll(
  personas: Persona[],
  issue: IssueSpec,
  tier: 'cheap' | 'deep',
  deps: RunDeps,
  ctx?: { counterArguments?: string[]; round?: number },
): Promise<PersonaPosition[]> {
  const out = await Promise.all(
    personas.map((p) =>
      deps.invoker.invoke(p, issue, tier, ctx).then((pos) => ({
        ...pos,
        embedding: pos.embedding.length ? pos.embedding : deps.embedder.embed(pos.text),
      })),
    ),
  );
  return out;
}

async function runRedTeam(
  adversaries: Persona[],
  issue: IssueSpec,
  lead: Faction | undefined,
  deps: RunDeps,
): Promise<RedTeamHit[]> {
  if (adversaries.length === 0) return [];
  const ctx = { counterArguments: lead ? [lead.positionSummary] : [] };
  const positions = await invokeAll(adversaries, issue, 'deep', deps, ctx);
  return positions.map((pos, i) => {
    const severity: RedTeamHit['severity'] =
      pos.confidence >= 0.8 && pos.citations.length > 0
        ? 'fatal'
        : pos.confidence >= 0.55
          ? 'material'
          : 'minor';
    // Rebutted iff the lead position carries citations and outweighs the attack.
    const rebutted = severity !== 'fatal' && pos.confidence < 0.7;
    return {
      id: `rt${i + 1}`,
      severity,
      claim: pos.text.slice(0, 280),
      byPersonaId: pos.personaId,
      rebutted,
      forcedRevision: severity === 'fatal' && !rebutted,
      falseAnalogy: /analogy|isomorph|maps to/i.test(pos.text),
    };
  });
}

function buildReviewerModel(reviewers: Persona[], options: CadeOptions): ReviewerModel | undefined {
  if (reviewers.length === 0) return undefined;
  const total = reviewers.reduce((s, r) => s + r.authority, 0) || 1;
  return {
    known: reviewers.length === 1,
    posture: options.posture ?? 'expected_value',
    reviewers: reviewers.map((r) => ({
      id: r.id,
      weight: r.authority / total,
      preferenceTags: r.priorsTag ? [r.priorsTag] : [],
    })),
    appealRobust: reviewers.length > 1,
  };
}

function numericAnswer(factions: Faction[], positions: PersonaPosition[]): number | undefined {
  if (positions.every((p) => p.stance === 0)) return undefined;
  // support-weighted mean stance of the winning faction's members.
  const lead = factions[0];
  if (!lead) return undefined;
  const members = positions.filter((p) => lead.memberIds.includes(p.personaId));
  if (members.length === 0) return undefined;
  const wsum = members.reduce((s, m) => s + m.stance * m.confidence, 0);
  const w = members.reduce((s, m) => s + m.confidence, 0) || 1;
  return wsum / w;
}

function dedupeIssues(issues: IssueSpec[]): IssueSpec[] {
  const seen = new Set<string>();
  const out: IssueSpec[] = [];
  for (const i of issues) {
    if (!seen.has(i.id)) {
      seen.add(i.id);
      out.push(i);
    }
  }
  return out;
}

function stripUndef<T extends object>(o: T): Partial<T> {
  const out: Partial<T> = {};
  for (const k of Object.keys(o) as (keyof T)[]) if (o[k] !== undefined) out[k] = o[k];
  return out;
}
