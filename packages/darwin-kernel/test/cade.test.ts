import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  runDetermination,
  filterByCompetence,
  selectPanel,
  clusterFactions,
  factionDistribution,
  jsDivergence,
  buildCertificate,
  packageForReviewer,
  hashEmbedder,
  relevance,
  type Persona,
  type IssueSpec,
  type Invoker,
  type PersonaPosition,
  type Candidate,
} from '../src/cade/index.ts';

const embedder = hashEmbedder(48);

// Stance/text by school of thought so same-prior minds cluster together.
const STANCE: Record<string, number> = {
  textualist: 0.8,
  purposivist: -0.7,
  law_and_economics: 0.5,
  realist: -0.4,
  comparative: 0.2,
  physics: 0.9,
};

/** Deterministic mock invoker: position derived from the persona's prior tag. */
const invoker: Invoker = {
  async invoke(persona, issue, tier, ctx): Promise<PersonaPosition> {
    const tag = persona.priorsTag ?? persona.role;
    const stance = persona.role === 'adversary' ? -1 : (STANCE[tag] ?? 0.1);
    const text = `${tag} position on ${issue.id}${ctx?.counterArguments?.length ? ' (revised)' : ''}`;
    const confidence = persona.role === 'adversary' ? persona.authority : Math.min(1, persona.reliability + 0.1);
    return {
      personaId: persona.id,
      stance,
      text,
      confidence,
      embedding: embedder.embed(tag), // identical tags → identical embedding → cluster
      citations: persona.authority >= 0.8 ? [`${tag}-cite-1`] : [],
      subQuestions:
        tier === 'cheap' && persona.id === 'p_posner' && issue.kind === 'financial'
          ? [
              {
                id: `${issue.id}__vol`,
                text: 'Is the implied-vol assumption sound?',
                kind: 'technical',
                requiredCompetence: { stochastic_calculus: 1, probability: 0.8 },
                materiality: 0.2,
              },
            ]
          : undefined,
    };
  },
};

function legalRoster(): Persona[] {
  const minds: Array<[string, string, number, number]> = [
    ['p_textA', 'textualist', 0.95, 0.8],
    ['p_textB', 'textualist', 0.85, 0.75],
    ['p_purpA', 'purposivist', 0.9, 0.8],
    ['p_purpB', 'purposivist', 0.8, 0.7],
    ['p_lae', 'law_and_economics', 0.88, 0.82],
    ['p_realist', 'realist', 0.7, 0.65],
    ['p_comp', 'comparative', 0.6, 0.6],
    ['p_posner', 'law_and_economics', 0.92, 0.85],
  ];
  const roster: Persona[] = minds.map(([id, tag, authority, reliability]) => ({
    id,
    name: id,
    role: 'authority',
    priorsTag: tag,
    authority,
    reliability,
    competence: { constitutional_law: 1, contracts: 0.8, conflict_of_laws: 0.7, civil_procedure: 0.5 },
  }));
  // A physicist with NO legal competence — should be excluded from a legal issue.
  roster.push({
    id: 'p_einstein',
    name: 'Einstein',
    role: 'discipline',
    priorsTag: 'physics',
    authority: 0.99,
    reliability: 0.9,
    competence: { physics: 1, stochastic_calculus: 0.9, geometry: 0.8 },
  });
  // Adversaries (red team) + a reviewer (tribunal).
  roster.push({
    id: 'p_adv1', name: 'OpposingCounsel', role: 'adversary', authority: 0.85, reliability: 0.8,
    competence: { constitutional_law: 0.9, conflict_of_laws: 0.8 },
  });
  roster.push({
    id: 'p_rev1', name: 'PresidingJudge', role: 'reviewer', priorsTag: 'textualist', authority: 0.9, reliability: 0.85,
    competence: { constitutional_law: 1, conflict_of_laws: 0.6 },
  });
  return roster;
}

const choiceOfLaw: IssueSpec = {
  id: 'clause_choice_of_law',
  text: 'Governing-law and forum-selection clause enforceability.',
  kind: 'legal',
  requiredCompetence: { conflict_of_laws: 1, contracts: 0.7, civil_procedure: 0.5 },
  materiality: 0.8,
  rosterClass: 'scotus',
};

// ---------- competence matching ----------
test('competence gate excludes the physicist from a legal choice-of-law issue', () => {
  const { eligible, excluded } = filterByCompetence(legalRoster(), choiceOfLaw, 0.12);
  assert.ok(eligible.some((p) => p.id === 'p_textA'));
  assert.ok(excluded.some((e) => e.persona.id === 'p_einstein'));
});

test('the physicist IS relevant to a derivatives calculation', () => {
  const einstein = legalRoster().find((p) => p.id === 'p_einstein')!;
  const derivatives: IssueSpec = {
    id: 'derivatives_calc', text: 'CVA on a payment swap', kind: 'financial', materiality: 0.7,
    requiredCompetence: { stochastic_calculus: 1, derivatives_pricing: 0.9, probability: 0.8 },
  };
  assert.ok(relevance(einstein, derivatives) > 0.2);
  assert.ok(relevance(einstein, choiceOfLaw) < 0.05);
});

// ---------- conclave selection ----------
test('selectPanel respects the seat cap and reports a marginal-value bound', () => {
  const tags = ['textualist', 'purposivist', 'law_and_economics', 'realist', 'comparative'];
  const candidates: Candidate[] = tags.map((tag, i) => ({
    persona: { id: `c${i}`, name: tag, role: 'authority', priorsTag: tag, authority: 0.8, reliability: 0.8, competence: {} },
    position: { personaId: `c${i}`, stance: STANCE[tag] ?? 0, text: tag, confidence: 0.8, embedding: embedder.embed(tag), citations: [] },
  }));
  const sel = selectPanel(candidates, 4, { diversityWeight: 0.6, infoGainStop: 0.08, hereticQuota: 0.08 });
  assert.ok(sel.seated.length <= 4);
  assert.ok(sel.marginalValueBound >= 0 && sel.marginalValueBound <= 1);
});

// ---------- factions + convergence ----------
test('same-school minds cluster; identical distributions have zero JS divergence', () => {
  const positions: PersonaPosition[] = [
    { personaId: 'a', stance: 0.8, text: 'textualist', confidence: 0.9, embedding: embedder.embed('textualist'), citations: [] },
    { personaId: 'b', stance: 0.8, text: 'textualist', confidence: 0.8, embedding: embedder.embed('textualist'), citations: [] },
    { personaId: 'c', stance: -0.7, text: 'purposivist', confidence: 0.85, embedding: embedder.embed('purposivist'), citations: [] },
  ];
  const factions = clusterFactions(positions, () => 0.8);
  assert.equal(factions.length, 2);
  const dist = factionDistribution(factions);
  assert.equal(jsDivergence(dist, dist), 0);
});

// ---------- certificate ----------
test('certificate confidence rises with lead support, robustness and small epsilon', () => {
  const weak = buildCertificate({ consideredCount: 50, seatedCount: 10, marginalValueBound: 0.4, saturated: false, adversariallyComplete: false, leadSupport: 0.4, jackknifeRobust: false });
  const strong = buildCertificate({ rosterClass: 'scotus', rosterComplete: true, consideredCount: 1000, seatedCount: 20, marginalValueBound: 0.02, saturated: true, adversariallyComplete: true, leadSupport: 0.85, jackknifeRobust: true });
  assert.ok(strong.confidence > weak.confidence);
  assert.match(strong.statement, /excluded mind/);
  assert.match(strong.statement, /scotus/);
});

// ---------- full engine ----------
test('runDetermination yields a determination with proof, certificate and preserved dissent', async () => {
  const det = await runDetermination(choiceOfLaw, legalRoster(), { invoker, embedder }, { now: () => '2026-06-29T00:00:00Z', maxRounds: 3 });
  assert.equal(det.issueId, 'clause_choice_of_law');
  assert.ok(det.factions.length >= 1);
  assert.ok(det.confidence >= 0 && det.confidence <= 1);
  // Einstein was excluded from the considered set.
  assert.ok(!det.proof.record.consideredPersonaIds.includes('p_einstein'));
  assert.ok(det.proof.record.excludedPersonaIds.includes('p_einstein'));
  // Content-addressed proof id, red team ran, tribunal model attached.
  assert.match(det.proof.id, /^cade_[0-9a-f]{40}$/);
  assert.ok(det.proof.record.redTeam.length >= 1);
  assert.ok(det.proof.record.reviewerModel);
  // Dissent preserved (more than one faction expected across schools).
  assert.ok(det.dissent.length >= 1);
});

test('financial determination summarizes its distribution, recurses councils, returns a numeric value', async () => {
  const finRoster = legalRoster().map((p) =>
    p.role === 'authority'
      ? { ...p, competence: { stochastic_calculus: 0.8, derivatives_pricing: 0.9, probability: 0.7, finance: 1 } }
      : p,
  );
  // give the physicist + an advisor finance competence so councils can seat
  finRoster.push({ id: 'p_quant', name: 'Quant', role: 'advisor', priorsTag: 'physics', authority: 0.85, reliability: 0.8, competence: { stochastic_calculus: 1, probability: 0.9 } });
  const issue: IssueSpec = {
    id: 'roi_estimate',
    text: 'Expected ROI of the structured note',
    kind: 'financial',
    materiality: 0.9,
    requiredCompetence: { finance: 1, derivatives_pricing: 0.8, probability: 0.7 },
    distribution: { samples: Array.from({ length: 1000 }, (_, i) => (i / 1000) * 0.2 - 0.02) },
  };
  const det = await runDetermination(issue, finRoster, { invoker, embedder }, { now: () => '2026-06-29T00:00:00Z', maxDepth: 2 });
  assert.ok(issue.distribution?.p50 !== undefined, 'distribution summarized');
  assert.ok(typeof det.value === 'number');
  // p_posner surfaced a vol sub-question on a financial issue → a council ran.
  assert.ok((det.proof.record.councils?.length ?? 0) >= 1, 'expert council recursed');
});

// ---------- advocacy firewall ----------
test('packageForReviewer preserves substance under a faithful restyle', async () => {
  const det = await runDetermination(choiceOfLaw, legalRoster(), { invoker, embedder }, { now: () => '2026-06-29T00:00:00Z' });
  const pkg = packageForReviewer(det, { embedder, restyle: (s) => `${s}` });
  assert.equal(pkg.semanticFidelity, 1);
  assert.ok(pkg.substancePreserved);
});
