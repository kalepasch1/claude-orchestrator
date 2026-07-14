PROJECT: tomorrow
# CORE CADE chain. Engines verified + bundled at outputs/install-cade-prediction.sh
# (8 modules,18 tests) + outputs/install-cade-publication.sh (8 modules,25 tests).
# Must land + apply the ledger migration before CADE_LEARNING_ENABLED does anything.

- id: cade-prediction-extract
  title: Land the verified CADE prediction engine into packages/cade-prediction
  material: no
  model: sonnet
  depends: []
  proof: `npx vitest run packages/cade-prediction` exits 0 AND `npm run build` exits 0
  prompt: |
    Land packages/cade-prediction/ from `BASE=$(pwd) bash outputs/install-cade-prediction.sh`
    (or copy outputs/cade-prediction-src/*). Pure, zero app deps. Keep 18 tests green.

- id: cade-publication-extract
  title: Land the verified CADE publication/SEO engine into packages/cade-publication
  material: no
  model: sonnet
  depends: []
  proof: `npx vitest run packages/cade-publication` exits 0 AND `npm run build` exits 0
  prompt: |
    Land packages/cade-publication/ from outputs/install-cade-publication.sh (tiered gate
    conservative n>=100/moderate n>=1000/full n>=5000 at >=80%+ECE<=0.05, article/seo/
    channels/bizDev/publishPlan/edgeEmbargo/fullPassReport). Keep 25 tests green.

- id: cade-prediction-ledger
  title: Prisma prediction ledger + record/resolve/score pipeline
  material: yes
  model: sonnet
  depends: [cade-prediction-extract]
  proof: `npx prisma validate` exits 0 AND `npx vitest run server/utils/cade/__tests__/ledger.test.ts` exits 0
  prompt: |
    Add Prisma CadePrediction/CadeOutcome/CadeScore (default-deny RLS, INSERT-only;
    idempotent migration; `npm run lint:migrations`). Add server/utils/cade/ledger.ts
    (record/resolve/score via scorePrediction) tested behind an injected client. Do NOT
    deploy the migration (OPERATOR).

- id: cade-expert-panel-feed
  title: Emit a Prediction from the determination/expert panel at ruling time
  material: yes
  model: opus
  depends: [cade-prediction-ledger]
  proof: `npm run build` exits 0 AND `npx vitest run server/utils/cade/__tests__/panelFeed.test.ts` exits 0
  prompt: |
    Wire the determination/expert panel (server/utils/cade/roster.ts + determination path)
    to emit a Prediction (per-expert p + ensemble consensus) into the ledger with horizon +
    resolutionSource on every formed view. Pure mapping tested; write via the ledger seam.

- id: cade-outcome-resolvers
  title: Outcome resolvers that pull realized results and auto-score
  material: yes
  model: sonnet
  depends: [cade-prediction-ledger]
  proof: `npm run build` exits 0 AND `npx vitest run server/utils/cade/__tests__/resolvers.test.ts` exits 0
  prompt: |
    Add server/utils/cade/resolvers.ts: pure resolvers mapping realized outcomes to
    CadeOutcome (regulatory releases/enforcement/rule proposals via corpus feeds; dockets;
    settlements; matched IOIs from ioiMesh as financial ground truth). Cron matches open
    predictions past horizon + scores via the ledger. Mock feeds in tests. No keys in code.

- id: cade-full-pass-trial
  title: First-full-pass trial - spin up expert bots, run the tournament, self-check
  material: yes
  model: opus
  depends: [cade-expert-panel-feed, cade-outcome-resolvers, cade-publication-extract]
  proof: `npm run build` exits 0 AND `npx vitest run server/utils/cade/__tests__/fullPassTrial.test.ts` exits 0
  prompt: |
    Add server/utils/cade/fullPassTrial.ts driving ONE complete pass on a RESOLVED backtest
    set, self-verifying every stage via packages/cade-publication fullPassReport (bots
    CREATED -> tournament RUN -> predictions EMITTED -> RESOLVED -> SCORED -> CALIBRATED ->
    RANKED -> publish-GATED). Any failed/missing stage immediately enqueues a high-priority
    fix (enqueueCodeImprovementRequest, source_bot 'cade-full-pass-trial'). Persist the
    FullPassReport for the operator email. Test all-green + a stubbed broken-stage path.

- id: cade-activate-now
  title: Activate the CADE learning loop - register crons + kickoff endpoint
  material: yes
  model: sonnet
  depends: [cade-full-pass-trial]
  proof: `npm run build` exits 0
  prompt: |
    Register CADE crons in nuxt.config.ts scheduledTasks (+ vercel.json): resolver/scoring
    sweep, nightly training loop, full-pass-trial (once on deploy then daily health check).
    Add POST /api/cade/kickoff (CRON_SECRET-gated). Learning/resolving/training crons
    read+score+reweight only (run when CADE_LEARNING_ENABLED=true, already set); publishing
    stays tier-gated + human-reviewed, edges embargoed. This makes CADE live.

OPERATOR:
  - Deploy the cade-prediction-ledger migration to prod (edetxpcoaiqlqrwyzltw) after review - until then no predictions can be recorded.
  - CADE_LEARNING_ENABLED=true is set; confirm CRON_SECRET in Vercel prod. Provide feed access for resolvers.
