PROJECT: apparently

# CADE moat + self-improvement consumers. apparently now CONSUMES the @darwin/kernel/cade
# core (the local position/recipient modules were extracted to the kernel). These tasks
# capture the proprietary training data and turn human touches into a learning signal.
# nuxt app: `npm run build` is the merge gate.

- id: cade-run-capture
  title: Emit every CADE run to a durable moat ledger (inputs → determination → outcome)
  material: yes
  model: sonnet
  depends: []
  proof: `npm run build` exits 0 AND `npx vitest run tests/engines/cade-run-capture.test.ts` exits 0
  prompt: |
    Add a durable capture of every real CADE opinion run: a migration for a `cade_runs` table
    (default-deny RLS, service insert) and `server/utils/cade-run-capture.ts` `captureRun(draft,
    context)` that records inputs (mandate, recipient, facts hash), the weakness + alignment
    ledgers, the determination + credential id, and the bots/roster used — leaving `outcome` null
    until known. Call it (fail-soft) at draft finalize. Mirror the beethoven `cade_run_ledger`
    schema so the two stores align. Unit test the row mapping. This is the moat data — start
    gathering NOW. CANDIDATE-SHARED with smarter/tomorrow.

- id: cade-outcome-backfill
  title: Record realized outcomes + actual RFIs/rulings against a captured run
  material: yes
  model: haiku
  depends: [cade-run-capture]
  proof: `npm run build` exits 0
  prompt: |
    Add `POST /api/legal-opinions/[id]/cade-outcome.post.ts` to set the realized `outcome`
    (prevailed / RFIs actually raised / ruling summary) on a `cade_runs` row. Reuse the existing
    service-client + fail-soft pattern from the other outcome endpoints. This closes the loop the
    twin/threshold/eval-mining all depend on.

- id: cade-override-training-signal
  title: Turn attorney overrides/edits into a bot-competence training signal
  material: yes
  model: sonnet
  depends: [cade-run-capture]
  proof: `npm run build` exits 0 AND `npx vitest run tests/engines/override-training.test.ts` exits 0
  prompt: |
    Add `server/engines/legal-bots/override-training.ts`: a PURE `deriveTrainingSignal(run,
    overrideOrEdit)` that converts each attorney override/edit/acceptance on a captured run into a
    labeled example — which bot/position was right vs corrected — and emits a competence delta per
    contributing bot (feeds beethoven `bot_recert`/knowledge aggregation). Unit-tested; no live
    model. The roster measurably improves every time a lawyer touches it, and the delta is auditable.

- id: cade-backlog-preregister
  title: Historical-backlog pre-registration — would-have-been win-rate before go-live
  material: yes
  model: sonnet
  depends: [cade-run-capture]
  proof: `npm run build` exits 0 AND `npx vitest run tests/engines/backlog-preregister.test.ts` exits 0
  prompt: |
    Add `server/engines/legal-bots/backlog-preregister.ts`: `preregister(candidate, historicalRuns)`
    that replays a candidate bot/determination-type against a held-out set of PAST captured runs with
    known outcomes and reports its would-have-been win-rate + calibration, so partners approve on
    evidence not faith. Pure over passed-in historical runs (no live model in the test). This is the
    safety rail that makes autonomous roster expansion approvable. Unit-tested.

OPERATOR:
  - Apply the `cade_runs` migration to the live apparently Supabase.
  - Backfill known past outcomes (accepted/rejected opinions, RFIs, rulings) into `cade_runs` to seed the twin + eval-mining + pre-registration harness.
