# CADE — Platform-Wide Implementation Handoff

**You are implementing the Consensus & Adversarial Determination Engine (CADE) across the Darwin
product portfolio: Apparently, Tomorrow, smarter, Pareto/2080, and the orchestrator.** The pure
engine is already built and tested in the shared kernel. Your job is to wire it into every relevant
surface, build the model-backed adapters, stand up the persona/roster + proof + calibration
infrastructure, finish the cross-cutting subsystems, and ship the "10–200X" infrastructure
improvements. This prompt is exhaustive — implement everything in it.

> Operating mode: work repo-by-repo through the orchestrator task queue. **Do NOT push to any
> production branch or run a production migration without the materiality gate + operator approval**
> (see §1). Land code on feature branches, keep tests green, and let the existing approval flow merge.

---

## 0. What already exists (do not rebuild)

`packages/darwin-kernel/src/cade/` — pure, zero-dependency, exported as `@darwin/kernel/cade`.
Verified: 8 CADE tests + 51/51 kernel tests pass; `tsc --noEmit` clean.

Public API you will consume (already implemented):

```ts
import {
  runDetermination, type RunDeps, type Determination,
  type Persona, type IssueSpec, type PersonaPosition,
  type Invoker, type Embedder, type CadeOptions,
  packageForReviewer, type PackageDeps,
  filterByCompetence, selectPanel, clusterFactions, buildCertificate, buildProofPack,
  hashEmbedder, summarize,
} from '@darwin/kernel/cade';

// runDetermination(issue, roster, { invoker, embedder }, options?, depth?) => Promise<Determination>
```

Key types (already defined — read `src/cade/types.ts`):
- `Persona{ id,name, role:'authority'|'discipline'|'advisor'|'adversary'|'advocate'|'reviewer',
  competence:Record<string,number>, authority:0..1, reliability:0..1, priorsTag?, exploration? }`
- `IssueSpec{ id,text, kind, requiredCompetence:Record<string,number>, materiality:0..1,
  rosterClass?, distribution?{samples:number[]} }`
- `Invoker.invoke(persona, issue, tier:'cheap'|'deep', ctx?) => Promise<PersonaPosition>`
- `PersonaPosition{ personaId, stance:number, text, confidence, embedding:number[], citations:string[],
  subQuestions?:IssueSpec[] }`  ← `subQuestions` are the recursive Expert-Council seeds.
- `Determination{ position, value?, confidence, dissent:Faction[], factions, certificate, proof, unsettled }`
- `CadeOptions{ relevanceThreshold, diversityWeight, infoGainStop, hereticQuota, maxRounds, maxDepth,
  convergenceEpsilon, sign, now }`

**The kernel owns the structure + math. You build the model-backed adapters (Invoker, Embedder) and
the per-product wiring. Never put model calls, DB calls, or product logic into the kernel.**

---

## 1. Operating rules & guardrails (read before writing code)

Per-repo conventions are in each repo's `CLAUDE.md` — obey them exactly. Highlights:

- **Apparently** (Nuxt 4 / Supabase / RLS): no hardcoded model strings — use `AI_MODELS` from
  `~/server/utils/ai-models.ts`; no raw `.from('table')` — use `useTypedClient()` /
  `useTypedServiceClient()`; all AI calls through `server/utils/ai.ts` (`callClaude`,
  `callClaudeStructured`) which already do retries/caching/logging; log every AI call via
  `ai-call-logger.ts`; RLS on every table; migrations idempotent + numbered.
- **Tomorrow** (Nuxt 3 / Prisma / Supabase): **migration name-check before landing** (table =
  `@@map` value, columns = camelCase field names unless `@map`); double-quote camelCase columns +
  snake `@@map` + `gen_random_uuid()` PKs; `npm run lint:migrations`; the **materiality classifier**
  (`gitAutomation.ts` + `self-improvement-runner.mjs`, kept in sync) — add every new sensitive path;
  `evaluateConstitution()` is the outer gate on any execution path; swap-only / ECP / §2(h)(7)
  posture unchanged; reuse `verifiableProof.ts` + `eventLog.ts` for proofs.
- **Pareto/2080** (Nuxt 3 / Prisma): pure engines in `server/utils/*` with `tests/*.test.js`
  (node:test), ESM, seedable RNG, money in USD; `$fetch as any` cast pattern; `layout:false` rule.
- **Orchestrator**: Python runner + Supabase + capability registry; respect `SPEC.md` invariants
  (upsert/ON CONFLICT, RLS, `privacy.scrub()` on user text, `provenance.record()` on publish,
  confidence gate before merge).
- **Proof signing**: set/҂reuse `DARWIN_SIGNING_PRIVATE_KEY_PEM` (Ed25519 PKCS8) as the stable
  anchor; `runDetermination(..., { sign:true })` signs the proof pack via the kernel anchor.
- **Cost discipline**: cheap model for the breadth pass, strong model only for synthesis + red team
  (see §2.3). Cache aggressively (§6.2). Enforce a per-determination cost ceiling + recursion depth
  limit + cycle detection (kernel caps `maxDepth`; you cap $ and wall-clock).
- **No autonomous money movement / filing / sending.** CADE *determines*; existing approval flows
  *act*. Constitution stays the outer bound.

---

## 2. Build the shared adapter layer (once per repo, thin)

Create `server/utils/cade/` (Apparently/Tomorrow/Pareto) or `runner/cade.py` consumers. Each repo
needs three adapters.

### 2.1 Embedder
`embedder.ts` — wrap the product's existing embedding path:
- Apparently/Tomorrow: Voyage (`voyage-3`, 1024-dim) used elsewhere in the repo. Return `number[]`.
- Pareto / fallback: `hashEmbedder(64)` from the kernel (already deterministic).
- Cache embeddings by `sha256(text)+model` in pgvector (Apparently `corpus` infra) /
  KV (Tomorrow `coordination_tasks`).

### 2.2 Invoker (the core model adapter)
`invoker.ts` implementing `Invoker.invoke(persona, issue, tier, ctx)`:
1. **System prompt = the persona's reasoning signature** (method/values/priors from `priorsTag` +
   a short grounded bio) + the hard rule: *"Every assertion must cite a real document from the
   retrieved set; if you cannot cite it, do not assert it."* + the **atemporal-grounding rule**
   (reason in your characteristic method over TODAY's facts/law; never rely on superseded
   authority).
2. **Retrieval grounding**: pull top-k from the persona's `corpus_filter` over the issue text
   (Apparently `corpus_documents`/`legal_bot_memories`; Tomorrow risk/regulatory corpus; Pareto:
   the relevant pure-engine outputs). Inject as the citable set.
3. **Tier → model** (use the repo's model constants, never literals):
   - `cheap` → Haiku (the breadth / standing-roster pass).
   - `deep` → Sonnet (debate rounds).
   - red-team personas + faction synthesis → Opus (strongest). Detect via `persona.role==='adversary'`
     or a `ctx.synthesis` flag you pass.
4. **Structured output** → `PersonaPosition`: `stance` (scalar; for numeric issues the persona's
   point estimate, else sign of their position), `text`, `confidence` (calibrated, ask for it),
   `embedding` (via §2.1), `citations` (real doc ids — validate they exist; drop hallucinated ones
   and downweight confidence), `subQuestions` (technical sub-issues → recursive councils).
5. **Prompt-cache** the static system+grounding prefix (Apparently `cacheSystemPrefix` /
   Anthropic `cache_control`).
6. **Log every call** via the repo's AI-call logger (cost/tokens/audit).

### 2.3 Model-tier + budget guard
`budget.ts`: per-determination cost ceiling, max personas at `deep` tier, wall-clock timeout,
recursion depth (pass `maxDepth` to options + your own cycle detector keyed on issue id). On ceiling
breach → return the best Tier-2 answer + flag `escalate`.

---

## 3. Persona roster + proof + calibration infrastructure

### 3.1 Roster store (the Standing Roster, Tier A)
Create a versioned persona library per domain. **Apparently** (Supabase, RLS, typed client):

```
cade_personas(
  id text pk, name text, role text, competence jsonb, authority numeric, reliability numeric,
  priors_tag text, exploration bool default false, corpus_filter jsonb, roster_class text,
  version int, active bool default true, created_at timestamptz )
```
**Tomorrow** (Prisma; name-check!): model `CadePersona` → `@@map("cade_personas")`, camelCase quoted
cols, `gen_random_uuid()` PK. **Pareto**: a versioned JSON roster in `server/utils/cade/roster/*.json`
is sufficient (lower stakes).

**Seed scripts** (`scripts/seed-cade-roster-*.ts`):
- Legal (Apparently/smarter): every U.S. Supreme Court Justice (historical + sitting), federal
  appellate giants, **state high-court justices** (the minimum baseline) — `role:'authority'`,
  `competence` derived from their opinion corpus, `corpus_filter` = a retrieval filter over their
  actual writings. Plus the **mosaic** (`role:'discipline'`): game theory, behavioral/institutional
  econ, philosophy, history, complexity, statistics, linguistics. Plus `role:'adversary'` archetypes
  (opposing counsel, skeptical regulator, bankruptcy trustee) and `role:'reviewer'` archetypes.
- Finance (Tomorrow/Pareto): every laureate economist + the great investors/risk managers/central
  bankers of all time (`authority`), the mosaic (physics/tail, complexity, statistics, decision
  theory) as `discipline`/`advisor`, adversaries (short-seller, SR 11-7 examiner), reviewers
  (examiner, rating agency, IC, LP).
- **Diversity must live in `priorsTag`/values, not in facts** (the Invoker gives everyone identical
  current facts; their disagreement basis is the prior). Tag `exploration:true` on a curated set of
  productive-heretic outliers.

### 3.2 Roster governance (treat the roster like code)
- Version every persona; re-ground against the live corpus on a schedule.
- **Golden-issue regression suite**: `tests/cade/golden/*.json` — issues with known-good
  determinations; CI fails if recall/precision drops. Seed ≥20 per domain.
- A roster CI check (drift): personas that stop predicting outcomes well get downweighted, not
  silently kept.

### 3.3 Proof store + verifier
- Persist `Determination.proof` (the `ProofPack`) per determination. Apparently: `cade_proofs`
  table; Tomorrow: reuse the `verifiableProof` storage pattern + a `CadeDetermination` model.
- **Unify the proof verifier UI**: extend Tomorrow's existing Proof Verifier page and Apparently's
  proof surface to verify a CADE proof pack (recompute `sha256Canonical(record)`, check the embedded
  Ed25519 key, render the Optimality Certificate + factions + red-team + councils).

### 3.4 Calibration flywheel (the compounding moat)
- `cade_calibration` table (per repo): determination id, persona ids seated, predicted vs realized
  outcome, timestamp. Write back from real outcomes — Apparently: opinion approved/rejected, clause
  litigated (`filing_outcome_log`); Tomorrow: ROI realized, loan performing, hedge outcome; Pareto:
  decision outcome.
- Update each persona's `reliability` (reputation-as-stake; mirror Tomorrow's `creditStore`). Track
  **advisor** reliability separately from **authority** reliability (§5.2). Feed into the next
  determination's panel selection automatically.

---

## 4. Per-platform wiring

For each, the pattern is: build `IssueSpec[]` (decompose the deliverable), call `runDetermination`
per unit (parallel), persist proof, surface the determination + dissent + certificate, optionally
`packageForReviewer` for delivery.

### 4.1 Apparently — comprehensive legal drafting & opinions
- Wrap `server/engines/legal-bots/` + `legal-opinion-engine.ts` + clause drafting: each clause / each
  opinion sub-issue → an `IssueSpec` (`kind:'legal'`, `rosterClass:'scotus'` etc.,
  `requiredCompetence` from a clause→competence classifier).
- The legacy `multi-pass-review.ts` Haiku→Sonnet becomes the **cheap tier** inside the Invoker.
- Grounding = `corpus_documents` + `legal_bot_memories` + `regulator_information_answers`.
- Emit the proof via the existing proof layer; show the Optimality Certificate to the user.
- New endpoints: `POST /api/cade/determine` (one issue), `POST /api/cade/draft` (decompose +
  determine a whole document), `GET /api/cade/proof/:id`.

### 4.2 The merged adaptive negotiation vehicle (Tomorrow War Room + smarter rooms) — **flagship**
Merge the War Room and the smarter negotiation rooms into one adaptive vehicle, with CADE as the
decision layer.
- Each clause / counter / proposed move = an `IssueSpec` (`kind:'negotiation'`). Decompose from the
  live clause set + the omni-channel ledger (email bridge / Zoom / Slack / portal redlines).
- **Reuse existing modules as CADE stages**: `replyStrategies` + `clauseDrafter` → candidate
  positions; `warGaming` → debate simulation; `votingEngine`/`consentWorkflowEngine` → faction
  consent; `counterpartyFingerprint` + `leverageScoring` + `responsePrediction` → the **Tribunal
  Model** (the modeled counterparty + arbitrator); `institutionalMemory`/`precedentEngine` →
  grounding + calibration.
- Output: recommended move + dissent ("what opposing counsel will argue") + a **BATNA-robust**
  certificate (Tribunal posture = minimax-robust when a breakdown is catastrophic, EV otherwise).
- Surfaces: a unified negotiation page that shows, per clause, the determination, the dissent, the
  reviewer model, and the signed proof. Single "adaptive vehicle" — one room object consumed by both
  apps via `@darwin/kernel/cade`.

### 4.3 Tomorrow — finance / risk / loan / insurance
- CADE sits **above** `riskFabric` + the pricers. Each ROI / rate / hedge structure / trigger =
  an `IssueSpec` (`kind:'financial'|'loan'|'insurance'`).
- **Monte Carlo bridge** (§5.3): populate `issue.distribution.samples` from the risk-fabric / pricer
  engines (10k+ paths, parameter uncertainty sampled). The economist personas argue over the
  distribution; positions surviving <5% of worlds are pruned (the Invoker should encode this).
- Bound every output with `evaluateConstitution()`; CADE proposes, Constitution bounds, human
  approves money. Reuse the proof layer + SDR/exam-pack outputs.

### 4.4 Pareto/2080 — high-stakes personal decisions
- Wrap decumulation sequencing, windfall allocation, Roth-conversion, buy-vs-rent, insurance
  crossover. Each = an `IssueSpec`; lighter roster + budget (smaller panels, `materiality` lower).
- **Monte Carlo substrate = existing pure engines** (`retirementMonteCarlo.js`, `uncertainty.js`).
- 5%-surface UX: show the single number + confidence; dissent + proof behind a "see the debate"
  toggle. Add an endpoint `GET /api/personal/cade/:decision` + a `Determination`-rendering tile.

---

## 5. Finish the cross-cutting subsystems

### 5.1 Anachronism Sentinel
`server/utils/cade/anachronism.ts`: a "superseded/overruled/disproven" index built from the corpus +
monitors (Apparently LegiScan/corpus-harvest/regulator feeds; Tomorrow regulatory-calendar). The
Invoker checks every cited authority against it and forces a persona to re-argue on live ground.
Flag + downweight any position leaning on dead authority.

### 5.2 Expert Councils (recursive) + Analogical Transfer + false-analogy guard
- The kernel already recurses on `PersonaPosition.subQuestions`. In the Invoker, when a persona hits
  a technical sub-question, emit a `subQuestion` `IssueSpec` (kind `'technical'`, advisor
  `requiredCompetence`). Recursion runs automatically (bounded by `maxDepth`).
- **Shared amicus briefs**: compute each council's technical brief ONCE per issue, cache by
  `(subQuestionEmbedding, corpusVersion)`, expose to all personas.
- **Analogical Transfer**: an Invoker operator that proposes structural isomorphisms from distant
  fields (multi-hop relevance expansion with decaying priors + a distant-field exploration quota).
  **Pair every analogy with a validity check**, and add a `role:'adversary'` "false-analogy hunter"
  to the red team. Track advisor reliability separately (§3.4).

### 5.3 Monte Carlo bridge
`server/utils/cade/monteCarlo.ts`: adapter from each app's simulation engine → `Distribution`
(10k–100k paths, sampled parameter uncertainty). The kernel summarizes (P5/P50/P95/tail) via
`summarize`. Pareto reuses `retirementMonteCarlo`; Tomorrow reuses risk-fabric.

### 5.4 Tribunal Model data layer
`server/utils/cade/tribunal.ts`: build reviewer personas from **legitimately public** data only
(opinions, dockets, public statements) — opinion citation preferences, reversal record, what has
won/lost. **Provenance gate**: a checkable invariant that rejects any non-public source. Posture =
EV or minimax-robust (caller choice). Emit `appealRobust` (don't win round one and lose on appeal).
For finance, "reviewers" = examiner / rating agency / IC / LP.

### 5.5 Advocacy Guild (firewalled delivery)
Implement the `PackageDeps.restyle(substance, reviewer, hedge)` adapter: an Opus call that repackages
the *fixed* determination for the modeled reviewer (tone/structure/citation emphasis), honest hedging
when `confidence<0.7`. `packageForReviewer` already runs the semantic-diff guard — if
`substancePreserved===false`, reject the restyle and retry. Human professional remains the authorized
final voice.

### 5.6 Continuous-learning monitors → living determinations
Wire the existing monitors (LegiScan, corpus-harvest, regulator-outreach, regulatory-calendar) as
triggers: when a monitored authority changes, re-run `runDetermination` on every stored proof whose
record cited it, diff the outcome, and alert the customer ("your opinion's basis just shifted").

---

## 6. The new 10–200X infrastructure improvements

### 6.1 One cross-product calibration flywheel
Because CADE lives in `@darwin/kernel`, route ALL products' calibration write-backs (§3.4) through a
single shared reliability store (kernel-side interface + per-product persistence). Apparently's legal
outcomes and Tomorrow's financial outcomes improve the same priors. This is the compounding moat —
build the shared interface, not per-app silos.

### 6.2 Standing-roster cache (free breadth)
Cache the cheap standing-roster positions + amicus briefs in pgvector (Apparently corpus infra) /
orchestrator capability store, keyed by `(issueEmbedding, corpusVersion, personaVersion)`. The
1,000-mind breadth pass becomes near-zero marginal cost → always-on is affordable. Add a cache-hit
metric.

### 6.3 Publish CADE as an orchestrator capability + self-tune the params
- `capability.py`: publish `cade.determine` as a capability (privacy.scrub + provenance.record per
  SPEC.md) so any project runs it.
- Use `bandit.py` + `eval_harness.py` against the golden-issue suite to A/B-tune
  `diversityWeight`/`infoGainStop`/`hereticQuota`/`convergenceEpsilon`. The engine tunes itself; gate
  param changes through the confidence gate.

### 6.4 Governance wiring (free outer bound)
Wrap every CADE execution path with `@darwin/kernel` governance: `evaluateConstitution` as the outer
gate, hash-chained receipts on each determination, materiality classification of all new CADE paths
added to BOTH classifiers (Tomorrow `gitAutomation.ts` + `self-improvement-runner.mjs`).

### 6.5 Red-Team-as-a-Service (new product surface)
Expose Stage 5 standalone: `POST /api/cade/red-team` takes an externally-drafted clause/opinion/
financial thesis and returns the adversarial findings + a signed "we tried to break it" proof.
High-margin lead-gen. Build the endpoint + a public results page in Apparently and Tomorrow.

### 6.6 Unify the proof verifier (see §3.3)
One verifier UI across Apparently + Tomorrow that validates any CADE proof pack offline.

---

## 7. Orchestrator coordination

- Decompose this handoff into tasks in the `tasks` queue (one per §-workstream per repo), respecting
  `kind` enum + state machine in `SPEC.md`.
- Record `outcomes.usd` per task; gate merges on `confidence.py`.
- Add CADE assessment dimensions to each app's self-assessment engine (Apparently/Tomorrow already
  have `runFullAssessment`): `assessCade` — golden-issue recall, calibration drift, cost-per-
  determination, cache-hit rate, proof-coverage %.
- Register CADE bots in the coordination layer (`coordination-client.ts` BOT_IDENTITIES +
  `ensureBotsRegistered`): `cade-roster-curator`, `anachronism-sentinel`, `calibration-flywheel-bot`,
  `living-determination-monitor`.

---

## 8. Acceptance criteria (per workstream — all must hold)

- `tsc --noEmit` clean; repo test suite green; `npm run lint:migrations` clean (Tomorrow); kernel
  `node --test` stays 51/51+.
- Golden-issue suite ≥ target recall (seed the baseline, ratchet up).
- Every new sensitive path added to the materiality classifier(s).
- Every CADE output ships a signed proof pack + Optimality Certificate; proof verifies offline.
- Cost ceiling + depth limit + cycle detection enforced; cheap-tier handles ≥90% of calls.
- No production migration / prod push without name-check + operator approval.
- RLS on every new Supabase table; no raw `.from()`; no hardcoded model strings; AI calls logged.
- Reviewer-modeling uses only provenance-checked public data.

## 9. Build order (phased)

1. **P0** — shared adapters (§2) + roster/proof/calibration infra (§3) in Apparently (richest
   corpus) + kernel-side shared interfaces.
2. **P1** — the **merged negotiation vehicle** (§4.2) end-to-end as reference vertical (most existing
   modules to reuse, highest leverage).
3. **P2** — Apparently legal drafting (§4.1) + Anachronism Sentinel (§5.1) + Tribunal data (§5.4) +
   Advocacy (§5.5).
4. **P3** — Tomorrow finance (§4.3) + Monte Carlo bridge (§5.3), Constitution-bounded.
5. **P4** — Pareto (§4.4) on the existing pure engines.
6. **P5** — the 10–200X infra (§6): flywheel, roster cache, capability + bandit tuning, governance
   wiring, Red-Team-as-a-Service, unified verifier.
7. **P6** — continuous-learning monitors / living determinations (§5.6) + hardening + assessment
   dimensions (§7).

## 10. Operator decisions to surface (do not guess)

- **Counsel sign-off** on judicial/arbitrator analytics data sourcing + provenance (§5.4) before
  scaling the Tribunal Model.
- **Prod env**: set `DARWIN_SIGNING_PRIVATE_KEY_PEM` (stable proof anchor) in each app's prod env;
  model budgets / cost ceilings.
- **Which vertical is the public flagship** for the marketing pages (the four `public/cade.html`
  pages already exist — link them once the matching vertical is live).
- **Claim posture**: market the *bounded certificate*, never infallibility (defensibility + the four
  pages already use this framing).

---

### Reference: minimal wiring example (drop-in shape for any product)

```ts
import { runDetermination, packageForReviewer } from '@darwin/kernel/cade';
import { cadeInvoker } from '~/server/utils/cade/invoker';     // you build (§2.2)
import { cadeEmbedder } from '~/server/utils/cade/embedder';   // you build (§2.1)
import { loadRoster } from '~/server/utils/cade/roster';       // you build (§3.1)
import { toIssues } from '~/server/utils/cade/decompose';      // you build (§4.x)

export async function determineDocument(doc: Doc, ctx: Ctx) {
  const roster = await loadRoster(doc.domain);
  const deps = { invoker: cadeInvoker(ctx), embedder: cadeEmbedder(ctx) };
  const issues = await toIssues(doc);                          // atomic contestable units
  const dets = await Promise.all(issues.map(i =>
    runDetermination(i, roster, deps, { sign: true, maxRounds: 4, maxDepth: 2 })));
  // persist dets[i].proof, surface dets[i].position + .dissent + .certificate,
  // then packageForReviewer(det, { embedder: deps.embedder, restyle }) for delivery.
  return dets;
}
```

**Implement all of §2–§7. Nothing in this document is optional.**
