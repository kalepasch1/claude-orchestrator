# MASTER HANDOFF — Tomorrow / Smarter / Apparently, staged through the Orchestrator

**Audience:** the executor of this work — a future Cowork session, the Claude Orchestrator runner, or Claude Code.
**Mandate:** complete, exhaustively, every improvement, task, wiring, suggestion, and human-action item agreed in the originating sessions. Build nothing by hand outside the orchestrator; *stage* work into the governed queue and let the runner execute it in isolated worktrees under cost caps, tests, and approval cards.
**Status of prerequisites (already done by Cowork, do not redo):**
- 5/95 keystone shipped + green: `tomorrow/server/utils/ux/decisionBudget.ts` (+ test, 13/13) and `tomorrow/scripts/lint-decision-budgets.mjs`.
- Staging layer built + dry-run-validated (27 tasks, DAG clean): `claude-orchestrator/runner/cowork_stage.py`, `claude-orchestrator/cowork-backlog/backlog.json`, `claude-orchestrator/COWORK_STAGING.md`.
- Legal drafts started: `tomorrow/legal/CONTINGENT_ECP_IDENTITY_RIDER.md` + `..._COMPARABLES_MEMO.md` (default-OFF, ECP-only).

---

## 0. Operating doctrine (applies to every task)

1. **5 / 95.** Every user-facing surface = 95% autonomous outcome (shown as fact) + 5% discretionary, regret-minimizing, pre-set "Recommended" knob + on-demand proof. The 5% gives the user agency and defensibility; it is not work you make them do. Enforced by `DecisionBudget` + the `FiveNinetyFive` wrapper. This applies to the exchange, the war room, **and** the attorney/Smarter surfaces.
2. **Loops, not features.** Most halves already exist; the value is the always-on loop that connects them and the network equilibrium that replaces per-org runs. Prefer wiring + cron + feedback over greenfield.
3. **Posture invariants (never violate; fail-closed).** Bilateral / non-CCP (N6); operator never holder/guarantor (N8); ECP-gated; swap-only allowlist; every autonomous action emits a C1 verifiable proof + compliance receipt; constitution + kill-switch bound all automation; counsel/model-risk gates the high-stakes items (see §7, §9).
4. **Contract-first.** Per repo, land the `contracts-*` task before its dependents; it pins the shared interfaces so parallel branches cannot diverge.
5. **Definition of done per task:** the acceptance test in the task prompt passes; typecheck/lint clean; proof/compliance emitted where applicable; no posture invariant broken; an `outcomes` row recorded.

---

## 1. System map

| Repo | Mac path | Stack | Role | Notes |
|---|---|---|---|---|
| **tomorrow** | `/Users/kpasch/Documents/tomorrow/tomorrow` | Nuxt4 + TS + Supabase + Anthropic | Risk-hedging platform (exchange, war room, perpetuals, mesh, verticals) | Working tree dirty (~1,543 files on `fix/ci-baseline`); build only via isolated worktrees |
| **smarter** | `/Users/kpasch/Documents/smarter` | Nuxt3 + TS + Pinia + Anthropic | AI legal/email workspace (matters, war room, trust dial) | No test runner yet; hardcoded model strings |
| **apparently** | `/Users/kpasch/Documents/apparently` | Nuxt4 + TS + Supabase + Anthropic | Compliance/legal-intel (licensing, regulator-intel, disclosure, email-triage, corpus) | Has Apparently→Tomorrow S2S already (rewards/gaming) |
| **claude-orchestrator** | `/Users/kpasch/Documents/beethoven/claude-orchestrator` | Nuxt + Supabase + Python runner | Control plane: task queue + Mac runner + dashboard | Supabase `eatfwdzfurujcuwlhdgj`; PAUSED by design |

---

## 2. Ground truth — what EXISTS (do not rebuild) vs what is MISSING

**EXISTS, verified — extend/wire, never recreate:**
- Tomorrow: public-data ingestion (`fdicDataFetcher`, `ffiecCdrDataFetcher`, `edgarMonitor`), one-identifier onboarding (`instantInstitution` → peer-consensus `constitutionCompiler` → `capitalLiberation/engine`), 5/95 substrate (`mandatePolicy`, `approvalQueue`, `GlassBox`, `DefensibilityDrawer`), perpetuals (`novelInstruments`, `perpetualLegs`, `embeddedOptionPerpetual`, `hedgePerpetualStack`, `mmHedgeOrchestrator`), `payoffDSL.ts` (1,407 lines) + `compositePrimitives`, mesh/credit/breach (`capacityFormation`, `defaultManagement`, `selfHealingRing`, `creditReliability`, `creditPassport`, `verifiableProof` C1), email/1-click approval (`approvalNotify` + `/api/approvals/inline/[token]`), verticals (bank/insurer/credit-union/gaming), Apparently S2S endpoints.
- Smarter: war-room bridge (`server/api/warroom/bridge.post.ts`, `tomorrowConnected`), standing/reliability signals, Policy Constitution + kill-switch + trust dial (`counsel_only/co_pilot/auto_pilot`), `apparentlyExport.ts`.
- Apparently: Apparently→Tomorrow S2S clients (budget-feed, provision, promote, overlay-link) + HMAC contract tests, `model-policy.ts`, coordination/outbox/self-improvement engines, corpus query + flywheel.

**MISSING / PARTIAL — the actual work (each is a backlog task in §4):**
- Tomorrow: no `DecisionBudget` enforcement wrapper; no closed perpetual lifecycle loop; no risk-spec payoff optimizer / perpetual-vs-discrete auto-choice; war-room auto-skip absent + learning-mode stubbed; mesh is small-N (no mesh-of-rings, no 1000-party path); credit is soft-rank (no hard gate/debt-ceiling/market pricing); breach remediation lacks pre-agreed-firm + auto-replacement wiring; hedging is per-bucket not per-contract; no lifecycle-adaptive hedging; cross-portfolio underwriting score not deployed; benefit receipts + real-time compliance-doc regen partial; onboarding inbound-only (no outbound pre-compute).
- Smarter: bridge not activated; ops-signal feed not emitted to Tomorrow; no test runner; hardcoded models; no DecisionBudget.
- Apparently: no `tomorrow-client.ts` / operational-risk outbox handler; the 4 detection engines don't emit signals to Tomorrow.

---

## 3. Execution model — how to run this (the replicable process)

All work flows through the orchestrator (full detail: `claude-orchestrator/COWORK_STAGING.md`):

1. The backlog is `claude-orchestrator/cowork-backlog/backlog.json` (27 tasks, contract-first, file-scoped prompts with acceptance tests).
2. **Dry-run (no writes):** `python3 runner/cowork_stage.py --backlog cowork-backlog/backlog.json` → validates DAG (deps resolve, no cycles, contract-first) and prints the plan.
3. **Commit (runner Mac, `SUPABASE_SERVICE_KEY` set):** add `--commit`. Idempotent — re-staging never duplicates.
4. The runner claims each `QUEUED` task whose deps are satisfied, builds it in `{repo}-wt/{slug}` (branch `agent/{slug}`), runs its acceptance test, gates on `confidence.py`, opens a PR, records `outcomes` (cost/tests). Material changes surface as `approvals` cards on the web dashboard.
5. Nothing spends until the runner is unpaused (see §8). Staged tasks sit harmless in `QUEUED`.

**Cross-app ordering:** land the three `contracts-*` tasks first (independent → parallel), then Tomorrow hub features, then the Smarter/Apparently tasks that consume Tomorrow's pinned contracts.

---

## 4. The backlog (27 tasks) — grouped, with acceptance criteria

> Canonical source is `backlog.json`; this is the human-readable index. Each task's full self-contained prompt (with file scope + acceptance test) is in that file. Build in dependency order.

### Stream A — Tomorrow: 5/95 doctrine
- `contracts-tomorrow` (deps: none) — pin `shared/contracts/{decisionBudget,xappSignal,warRoomSync,perpLifecycle,contingentIdentity}.ts`. AC: typecheck passes; interfaces exported + stable.
- `p0-decision-budget-wrapper` — `FiveNinetyFive.vue` (Outcome/One-knob/Proof); wire `decisionBudget` to existing UX telemetry (`magicMomentTracker`, `uxExperimentRunner`); fix the 2 declared violations (onboarding/institution 6→3, war-room 8→5); make the lint blocking for declared surfaces. AC: 0 declared-surface violations; decisionBudget test green.
- `p0-mandate-collapse` — replace `pages/app/mandate.vue` (105 controls) with regret-minimizing inferred mandate + disclosure; preserve `mandatePolicy` round-trip. AC: mandate within budget 3; mandate API tests pass.
- `trust-ratchet` — per-user auto-graduation generalizing `approvalQueue` learning-mode; budgets recompute to the user's trust frontier. AC: graduation-after-N + per-user frontier tests.

### Stream B — Tomorrow: perpetual universe
- `perp-lifecycle-loop` — cron: drift→`proposeHedge`→`reStrikePerpetualLeg`→re-price→re-prove, honoring the resolution-zone guard. AC: drift sim drives end-to-end; guard blocks in-zone re-strike.
- `composite-payoff-compiler` — risk-spec→payoff optimizer over `payoffDSL`; perpetual-vs-discrete auto-choice; stacking grammar via `composeProgram`; fail-closed allowlist+backtest. AC: returns allowlist-valid instrument + backtest + rationale; picks discrete for one-off with cost delta; rejects un-backtested composite.
- `funding-equilibrium` — cross-book funding optimizer (marginal hedge cost falls as book grows). AC: offsetting demand lowers computed marginal cost; guards conserved.
- `instrument-discovery-loop` — auto-spawn perpetual/embedded/gradient variant tree per generated underlying; Pareto-promote; fail-closed. AC: new underlying → backtested variants; failing variant never promoted.

### Stream C — Tomorrow: kill the war room
- `warroom-autoskip` — route low-novelty/low-risk/known clauses to email/1-button; wire stubbed learning-mode into a per-user auto-approve frontier; counsel-needed signal. AC: gated clause skips room; failing clause opens it; frontier widens with approvals.
- `warroom-attorney-cockpit` — at-market badges; pre-computed ZOPA + market-median midpoint; pre-call briefing pack; post-counsel one-button close (fires `closingWorkflow` + `docusign`). AC: only out-of-market clauses surface; midpoint attached; one-button advances to send_for_signature.

### Stream D — Tomorrow: blind, immaterial-breach mesh
- `mesh-of-rings` — hierarchical netting composing small-N rings → 100s–1000s-party dispersion, posture-clean (N6); breach-resilience metric. AC: 1000-party sim disperses; max single-party impact <1%; `failingInvariants` still hold.
- `credit-hard-gate` — min-tier admission (user + Tomorrow set); debt-ceiling absorbing penalty (portable in passport); risk-priced participation; hedgeable passport. AC: sub-tier denied/priced wider; serial defaulter recovery capped.
- `breach-remediation` (deps: mesh-of-rings, credit-hard-gate) — on breach: auto-source replacement (`selfHealingRing`+`discoverPairings`), open pre-agreed shared-cost matter via Smarter bridge, penalize on reveal, resume contract. AC: sim breach → replacement + matter + penalty + resume in one flow.

### Stream E — Tomorrow: the underwriting flywheel (the moat)
- `per-contract-hedging` — per-loan/policy risk-vector extraction → contract-bound hedge (not per-bucket). AC: loan tape → one hedge per contract w/ provenance, tighter than baseline.
- `lifecycle-adaptive-hedging` (deps: per-contract-hedging) — consume Apparently loan-state signals (`xappSignal`) → `reStrikePerpetualLeg` (stop on removal, increase on degrade). AC: sim default stops hedge; degrade increases; each with proof.
- `underwriting-score` (deps: per-contract-hedging) — cross-portfolio proprietary score (firm/geo/segment/global) → origination-embedded hedge quote (bps) via Apparently bank bridge + peer benchmark. AC: candidate loan → score + hedge-to-X + bps + percentile; backtests vs outcomes.

### Stream F — Tomorrow: demand + proof
- `benefit-receipts` — full benefit cascade (capital freed / vol reduced / earnings uplift) + event-time avoided-loss receipts + emergent-benefit discovery + real-time compliance-doc regeneration (SRT/ASC 815/RBC/constitution chained to C1). AC: sim event → defensible avoided-$ receipt w/ proof; re-opt regenerates chained docs.
- `outbound-onboarding` — pre-compute `OnboardingPackage` for ingested FDIC entities + personalized click-to-arm URLs; shadow-mode 60–90d pre-commitment receipt. AC: one identifier → full value surface + shadow receipt, no further input.
- `legal-identity-docs` (kind: legal) — expand the contingent-identity doc set (ISDA integration language, IOI anonymity schedule, Identity Custodian agreement, breach-remediation engagement letter, finalize comparables memo). AC: docs under `legal/`, cross-reference `contingentIdentity.ts`, DRAFT/counsel-execution headers, default-off.

### Stream G — Smarter
- `contracts-smarter` (deps: none) — add a vitest harness (currently none); pin `types/integration.ts` mirroring Tomorrow's `warRoomSync`/`xappSignal`. AC: `npm test` runs; smoke + contract-shape tests pass.
- `smarter-warroom-bridge-activate` — complete `bridge.post.ts` live path against the contract; `tomorrowConnected` flow; remediation-firm matter hook for Tomorrow's `breach-remediation`. AC: push/pull round-trips vs contract mock; remediation matter created from breach payload.
- `smarter-opsignal-feed` — emit standing/reliability/issue degradation as `xappSignal` to Tomorrow (PII-barrier clean). AC: degradation event → well-formed signal excluding PII.
- `smarter-model-policy` (kind: refactor) — centralize hardcoded `MODELS` into `model-policy.ts` (mirror Apparently). AC: no literal `claude-*` strings outside policy; `selectModel` tests.
- `smarter-5-95` — apply DecisionBudget over the existing trust dial; collapse advanced controls behind disclosure. AC: war-room + matter surfaces within budget.

### Stream H — Apparently
- `contracts-apparently` (deps: none) — pin `shared/contracts/tomorrow-signal.ts` + outbox handler interface; add fixed-vector HMAC contract test. AC: `npm test` passes incl. signing test.
- `apparently-tomorrow-client` — `server/utils/tomorrow-client.ts` (HMAC signer) + `outbox/handlers/operational-risk-handler.ts` (retry/dead-letter); information-barrier allowlist. AC: signed signal round-trips; non-allowlisted fields stripped pre-egress.
- `apparently-signal-emitters` (deps: apparently-tomorrow-client) — wire licensing-renewal / regulator-intel / disclosure / email-triage to emit `xappSignal` on their existing triggers. AC: each engine emits on trigger; barrier-clean.

---

## 5. Cross-app wiring contracts (the shared interfaces — pin first)

| Interface | Home | Consumed by | Purpose |
|---|---|---|---|
| `decisionBudget.ts` | tomorrow `shared/contracts` | tomorrow surfaces, smarter-5-95 | surface budgets + Outcome/One-knob/Proof props |
| `xappSignal.ts` | tomorrow `shared/contracts` | apparently client + emitters, smarter ops-feed, tomorrow lifecycle-adaptive | operational-risk-signal payload `{ts,eventType,severity,orgId,affectedEntity,metadata}`; PII-barrier enforced |
| `warRoomSync.ts` | tomorrow `shared/contracts` | smarter bridge, tomorrow breach-remediation | war-room push/pull + remediation matter |
| `perpLifecycle.ts` | tomorrow `shared/contracts` | perp lifecycle loop, compiler | drift→propose→re-strike→re-price→re-prove events |
| `contingentIdentity.ts` | tomorrow `shared/contracts` | contingent-identity, legal docs | default-OFF flag + contingent-reveal state machine |

**Drift guard (stage as a follow-up `self` task):** a CI lint across all three repos that fails if a local copy of any shared interface drifts from the canonical Tomorrow definition.

---

## 6. Program-level 10–200X improvements — also stage these

Beyond the 27 tasks, stage these as additional backlog items (they compound across all apps):

1. **ROI-ranked build queue.** Feed each task's *realized* business value (capital-freed / avoided-loss from `hedgeAttributionEngine`) back into the runner's bandit reward (not just `outcomes.usd` cost), so the swarm builds highest-$-impact features first.
2. **Unified autonomy-budget package.** Smarter's trust dial + Tomorrow's DecisionBudget + Apparently's materiality gate are the same primitive three times. Extract one shared `autonomy-budget` package that all three apps **and** the orchestrator's approval-card logic consume. One 5/95 engine governing everything.
3. **Self-staging loop.** A `kind=self` task that reads each repo's lint/test debt (e.g., the 139 undeclared over-budget surfaces the DecisionBudget lint found) and auto-generates backlog tasks to fix them — the backlog replenishes itself, mirroring Apparently's `corpus_gaps` flywheel.
4. **One shared corpus/credit service** across all three apps (already half-true via the deployed corpus v2) so risk scoring, legal authority, and credit passports are computed once and reused — the cross-app data moat compounds super-linearly with users.
5. **`/api/queue` + `make stage`.** Add the missing web endpoint (SPEC.md promises it) + a one-command wrapper so the dashboard and humans can stage without the CLI.

---

## 7. Legal workstream

- Drafts in place (default-OFF, ECP-only, opt-in): `tomorrow/legal/CONTINGENT_ECP_IDENTITY_RIDER.md`, `..._COMPARABLES_MEMO.md`. Built on proven comparables: undisclosed-principal doctrine (Restatement (Third) of Agency §§6.02–6.03), escrow custodian, anonymous give-up trading, syndicated-loan agency.
- Complete via the `legal-identity-docs` task: ISDA Schedule/Confirmation integration language; IOI Anonymity Disclosure Schedule; Identity Custodian / Escrow-Agent Agreement; unanimously-pre-agreed Breach-Remediation Engagement Letter; finalized validity memo.
- **Controlling rule (must survive in code + docs):** anonymity is counterparty-to-counterparty only; the platform and regulators are never blind. Preserve ECP verification, KYC/CIP + OFAC screening, and CFTC Parts 43/45/46 swap reporting/recordkeeping at all times. The Rider §7 controls over the entire Rider.
- **Gate:** CFTC/derivatives counsel + AML counsel sign-off against the memo §4 checklist before the `contingent-identity` feature flag is enabled for any live transaction. Code ships the flag **off**.

---

## 8. Human action items (cannot be done by the executor agent — route to the operator, Piper)

1. **Repo paths / project rows** — confirm the three `repo_path`s in `backlog.json` match the runner Mac; register any not yet in the orchestrator `projects` table.
2. **Failover account login** (one-time): `CLAUDE_CONFIG_DIR=~/.claude-heretomorrow claude login`.
3. **Commit the backlog** on the runner Mac: `python3 runner/cowork_stage.py --backlog cowork-backlog/backlog.json --commit`.
4. **Restart + unpause the runner** per `ACTIVATION.md` (load spend-capped code; lift kill switch). Optionally set `CLAUDE_MAX_USD_PER_DAY/HOUR`, `MAX_PARALLEL`.
5. **Approve material-change cards** on the web dashboard as tasks run.
6. **Legal:** obtain CFTC + AML counsel sign-off (memo §4) and execute the contingent-identity documents before enabling the feature.
7. **Secrets/env:** set `TOMORROW_WARROOM_API_URL/KEY` (Smarter), `TOMORROW_API_BASE_URL` + `REWARDS_S2S_SECRET`/`GAMING_S2S_SECRET` (Apparently), and any new S2S secret for the operational-risk signal — keep counsel-gated feature flags off until sign-off.

---

## 9. Guardrails & definition of done (every task)

- Posture invariants hold (N6 bilateral/non-CCP, N8 operator-not-holder/guarantor, ECP-gated, swap-only allowlist, fail-closed).
- Every autonomous action emits a C1 verifiable proof + compliance receipt; every override logged; constitution + kill-switch bound automation.
- DecisionBudget lint passes for touched declared surfaces; no new metric renders without a proof binding.
- For Streams B/D/E: new instruments/scores backtest and fail-closed on gaps.
- For high-stakes work (mesh, contingent-identity, underwriting advice, capital/benefit claims): independent review pass + the relevant counsel/model-risk gate; benefit/capital figures are estimates-with-methodology in the proof drawer, never guarantees; customer/contract data handled under privacy review.
- Each task records an `outcomes` row (tests + cost) before DONE/MERGED; merges only past the confidence gate.

---

## 10. Suggested sequence

`contracts-tomorrow` + `contracts-smarter` + `contracts-apparently` (parallel) →
Stream A (5/95) ∥ Stream B (perpetuals) ∥ Stream C (war room) →
Stream D (mesh) → `breach-remediation` (needs Smarter bridge activated) →
Stream E (underwriting; needs Apparently client + emitters) →
Stream F (demand/proof) + `legal-identity-docs` →
program-level improvements (§6) →
flip `contingent-identity` flag on only after counsel sign-off (§7).

**First three highest-ROI:** finish the autonomous loops (perp lifecycle cron, war-room learning frontier, Apparently→Tomorrow signal→re-strike); origination-embedded hedge quoting (`underwriting-score`); outbound pre-computed onboarding. Then everything compounds.

---
*This handoff is self-contained. Start at §3 to stage, §4 for the work, §8 for the human gates. The canonical machine-readable backlog is `claude-orchestrator/cowork-backlog/backlog.json`; the process is `claude-orchestrator/COWORK_STAGING.md`.*
