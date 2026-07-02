PROJECT: apparently

# CADE improvement wave (10–200X levers) — built as app-side features on the reference legal
# vertical, around the already-built @darwin/kernel/cade. Generalize to tomorrow/smarter/pareto after.
# Prereqs: the core CADE wiring (first wave: cade-invoker, cade-determine-legal, cade-proof-store,
# cade-calibration-writeback). Spec: claude-orchestrator/CADE_IMPLEMENTATION_HANDOFF.md.
# Repo rules: AI via server/utils/ai.ts; AI_MODELS constants; typed Supabase clients; RLS; log AI calls.

- id: cade-difficulty-router
  title: Difficulty router — settled vs contested gate before any panel runs
  material: no
  model: sonnet
  depends: [cade-determine-legal]
  proof: `npx vitest run server/utils/cade/__tests__/router.test.ts` exits 0
  prompt: |
    Build server/utils/cade/router.ts: a cheap learned/heuristic classifier that predicts, from the
    IssueSpec + a single Haiku probe + self-precedent hits, whether an issue is SETTLED (return one
    cheap determination) or CONTESTED (run full runDetermination). Wire it as the entry gate in the
    determine path. Target: skip the full panel on >=80% of issues. Test: settled-looking issues take
    the cheap path, contested ones escalate; record a routing decision in the proof record. See
    HANDOFF §6.2 + chat improvement #6.

- id: cade-disagreement-budget
  title: Disagreement-driven dynamic compute budget
  material: no
  model: sonnet
  depends: [cade-determine-legal]
  proof: `npx vitest run server/utils/cade/__tests__/dynamic-budget.test.ts` exits 0
  prompt: |
    Build a wrapper that allocates rounds/seats proportional to live faction divergence: stop early on
    quiet consensus, add rounds + recruit seats when JS-divergence between rounds stays high (call
    runDetermination iteratively with escalating maxRounds/maxSeats, reusing kernel convergence
    signals). Test: a low-disagreement issue terminates in fewer rounds than a high-disagreement one.
    See chat improvement #7.

- id: cade-minimal-flip
  title: Minimal-flip sensitivity proof per determination
  material: no
  model: sonnet
  depends: [cade-determine-legal]
  proof: `npx vitest run server/utils/cade/__tests__/minimal-flip.test.ts` exits 0
  prompt: |
    Build server/utils/cade/sensitivity.ts: for a determination, perturb each input (fact / cited
    authority / assumption) and re-run the cheap tier to find the smallest change that flips the
    outcome; attach the minimal-flip set to the proof record + surface it. Test: a known brittle
    determination reports a small flip set; a robust one reports a large/empty set. See chat #3.

- id: cade-mirror-determination
  title: Mirror determination — run CADE as the opposing side
  material: no
  model: sonnet
  depends: [cade-determine-legal]
  proof: `npx vitest run server/utils/cade/__tests__/mirror.test.ts` exits 0
  prompt: |
    Add a mode that runs the same IssueSpec with the adversary objective + an opposing-counsel roster,
    producing the other side's strongest position and where it diverges from ours. Surface as
    "anticipated opposing case". Test: mirror returns an opposed determination + a divergence summary.
    See chat #5.

- id: cade-model-diversity-seats
  title: Model-diversity seats (decorrelated base models on the panel)
  material: no
  model: sonnet
  depends: [cade-invoker]
  proof: `npx vitest run server/utils/cade/__tests__/model-diversity.test.ts` exits 0
  prompt: |
    Extend the invoker to honor a persona `backend` tag so a configurable minority of seats run on a
    genuinely different base model (decorrelating failure). Record backend per seat in the proof. Test
    (mocked backends): a mixed-backend panel records >1 distinct backend and still produces a valid
    determination. See chat #4.

- id: cade-meta-redteam
  title: Meta red-team — attack the engine, not the clause
  material: no
  model: sonnet
  depends: [cade-invoker]
  proof: `npx vitest run server/utils/cade/__tests__/meta-redteam.test.ts` exits 0
  prompt: |
    Build a harness that probes CADE itself for corpus prompt-injection, citation spoofing, poisoned
    personas, and roster drift; emit findings + a hardening report. Run it in CI against seeded
    attacks. Test: each seeded attack is detected. See chat #10.

- id: cade-self-precedent
  title: Self-precedent — memoize whole determinations as retrievable authority
  material: yes
  model: opus
  depends: [cade-proof-store]
  proof: `npm run gen:types && npx vitest run server/utils/cade/__tests__/self-precedent.test.ts` exits 0
  prompt: |
    Add cade_precedents (issue_embedding vector, determination_id, position, proof_id, version) with
    RLS. On a new issue, retrieve near-duplicate prior determinations; if similarity >= threshold,
    reuse the panel + proof and re-litigate only the delta (feed the prior as authority). Guarantees
    cross-deal consistency. Test: a near-duplicate issue reuses precedent + only re-runs the delta; a
    novel issue does not. See chat #1.

- id: cade-joint-consistency
  title: Joint/global consistency solver across a document's determinations
  material: no
  model: opus
  depends: [cade-determine-legal]
  proof: `npx vitest run server/utils/cade/__tests__/joint-consistency.test.ts` exits 0
  prompt: |
    Build a global pass over the clause-dependency graph that detects + reconciles locally-optimal but
    jointly-contradictory per-clause determinations into a coherent whole (constraint satisfaction;
    re-run conflicted units with the conflict as context). Test: an injected cross-clause contradiction
    is detected and resolved. See chat #12.

- id: cade-conformal-guarantee
  title: Conformal coverage guarantee on CADE confidence
  material: no
  model: opus
  depends: [cade-calibration-writeback]
  proof: `npx vitest run server/utils/cade/__tests__/conformal.test.ts` exits 0
  prompt: |
    Build server/utils/cade/conformal.ts: calibrate determination confidence against realized-outcome
    history (split-conformal) so the certificate can state a statistical coverage rate ("right >= X%
    at this confidence, on held-out outcomes"). Add to the Optimality Certificate output. Test:
    coverage holds on a held-out synthetic outcome set within tolerance. See chat #9.
    NOTE: guarantees are only meaningful once enough real outcomes accumulate (see OPERATOR).

- id: cade-outcome-benchmark
  title: Outcome-sourced golden benchmark (losses become tests)
  material: yes
  model: sonnet
  depends: [cade-calibration-writeback]
  proof: `npx vitest run server/utils/cade/__tests__/outcome-benchmark.test.ts` exits 0
  prompt: |
    When a determination is later proven wrong (outcome write-back), auto-append a golden-issue test
    capturing it. Persist to the golden set + CI. Test: a simulated wrong-outcome event creates a new
    golden case that the suite picks up. See chat #11.

- id: cade-consensus-embed-kit
  title: Consensus-as-an-API embed kit (metered CADE for third parties)
  material: no
  model: sonnet
  depends: [cade-determine-legal]
  proof: `npx vitest run server/api/cade/__tests__/embed.test.ts` exits 0
  prompt: |
    Expose a metered, CORS-validated public embed endpoint that runs a bounded CADE determination on a
    third-party question and returns the determination + signed proof (compute-only; no privileged
    data). Reuse the repo's existing embed-kit pattern. Test: a public embed call returns a determination
    + proof and is rate/cost-bounded. See chat #13.

- id: cade-self-play-library
  title: Self-play argument invention → novel-argument library
  material: yes
  model: opus
  depends: [cade-outcome-benchmark, cade-meta-redteam]
  proof: `npx vitest run server/utils/cade/__tests__/self-play.test.ts` exits 0
  prompt: |
    Build an offline self-play loop: proponents vs red team co-train over the golden set; any argument
    that beats the current best (survives the red team + improves outcome prediction) is promoted into
    cade_argument_library (with RLS) and made retrievable to personas. Bounded iterations + cost gate.
    Test: a seeded self-play round promotes exactly the arguments that beat the incumbent. The highest-
    ceiling lever — stage after the router + precedent layers pay for the compute. See chat #2.

OPERATOR:
  - Conformal guarantees need accumulated real outcomes — gate the public-facing accuracy claim until N held-out outcomes exist.
  - Self-play (cade-self-play-library) is compute-heavy and offline — confirm a cost budget + run cadence before enabling.
  - Vertical replication (tax / M&A diligence / patent / audit / medical) is a roadmap-level program needing scoping + possibly new repos — not queued here.
  - Pure-kernel primitives (similarity helper for self-precedent, conformal math, constraint solver) may be lifted into @darwin/kernel/cade later for reuse — kernel lives in claude-orchestrator (no project enum slot); route as a kernel task.
