# MISSION: Make the orchestrator generate, optimize, and deploy its own prompts — permanently, without being asked

You are working in `~/Documents/beethoven/claude-orchestrator`. This prompt is ADDITIVE to PROMPT-backlog-blitz.md (which may still be running — do not duplicate its items; check its report/commits first). Everything here builds on existing modules — extend, never fork: `planner.py`, `intake_watcher.py`, `self_review.py`, `meta_loop.py`, `eval_harness.py`, `knowledge_embed.py`, `learn_from_merges.py`, `prompt_distillation.py`, `bandit.py`, `causal_attribution.py`, `agentic_coders.py`, `generator_feedback.py`. Repo conventions apply: ORCH_ config keys via `fleet_config`, no secrets, fail-soft, 20+ tests per new module, propagate via git + `fleet_control`.

## WHY (verified diagnosis — the meta-layer exists but the chain is broken)

- The prompt-generation layer (`self_review`, `meta_loop`, `improve` lane, `intake_watcher`, `eval_harness`) runs downstream of the kill switch and spent most of its life paused. It also dead-ends: proposals become approval cards and queue rows that a broken merge pipeline never ships.
- The shared-knowledge loop is polluting, not expediting: `learn_from_merges.py` appended a raw usage-limit banner ("You've hit your weekly limit · resets Jul 8 at 6am") into CLAUDE.md/README as a "learning," and `planner.py` now injects that into future prompts. Embeddings are 429-throttled to keyword fallback; `.runtime/knowledge/` is empty; auto-extract-after-merge was never built.
- Operator-authored prompts (like PROMPT-backlog-blitz.md) are run as single serial Claude Code sessions instead of flowing through `intake/` → planner DAG → parallel routed execution.
- `bandit.py` learns from outcomes contaminated by rate-limited and toolchain-failed runs, so routing never actually improved.

## PART A — THE PROMPT FACTORY (objective → optimal prompt → intake → deploy)

A1. `runner/prompt_factory.py` (new periodic job, every 4h, gated like other generators by drain_mode and the meta:product cap):
   - Inputs: open objectives (existing `objective`/portfolio rows), KPI gaps from the scoreboard (Part D), and top unresolved blockers.
   - For each, generate a contract-first master prompt via `planner.py`, assembled by A2, and emit canonical intake files to `intake/factory-<slug>.md` (dependency-linked, material-flagged, model-routed, with a machine-checkable `proof:` line — no task without a proof command).
   - Idempotent by slug; never exceeds `ORCH_FACTORY_MAX_OPEN` (default 3) unshipped factory DAGs at once.
A2. `runner/prompt_assembler.py`: single composition point for EVERY prompt the orchestrator sends to any coder (Claude Code, aider, gemini, deepseek). Layers, in order: stable cached prefix (`caching.py`) → distilled per-project brief (≤4KB, from `prompt_distillation.py`) → top-k knowledge snippets (`knowledge_embed.inject`, quality-gated per Part B) → conventions/DO-AVOID → task spec. Refactor `claude_cli.py` / `agentic_coders.py` call sites to use it. Log assembled-prompt token counts to outcomes.
A3. Operator drop-box: any `PROMPT-*.md` dropped in repo root or `intake/` that is NOT canonical format gets auto-decomposed by `intake_watcher.py` (extend it) through `planner.py` into a DAG — so a human pasting a big prompt file is just another intake source. Manual serial Claude Code sessions are reserved for fleet-down recovery only; add this rule to CLAUDE.md.

## PART B — FIX THE KNOWLEDGE LOOP (shared code knowledge that actually expedites)

B1. Quality gate in `learn_from_merges.py` before anything is written to CLAUDE.md/README or embedded: reject content matching failure/limit/banner patterns (usage limits, HTTP errors, apologies, "as an AI"), require the extraction to parse as convention/do-avoid/snippet structure, and grade with a cheap model ("is this a reusable engineering learning? yes/no + confidence"). Quarantine rejects to `.runtime/knowledge/rejected.jsonl`.
B2. One-time cleanup task: strip the garbage "Learned from merged work" blocks (usage-limit banners, chatty preambles) from CLAUDE.md, README.md, SPEC.md; keep the two legitimate convention lists.
B3. Auto-extract after every merge (the unbuilt roadmap item): on merge-train success, extract {pattern, files, why, proof} from the diff, quality-gate (B1), embed via `knowledge_embed.extract`. Add rate-limit-aware batching with exponential backoff for the embed provider and a local fallback (ollama embeddings if present) so 429s degrade to delayed embedding, not keyword-only forever.
B4. Retrieval telemetry: when `inject()` supplies snippets, record knowledge_ids on the outcome row; nightly, compute reuse hit-rate and whether knowledge-assisted tasks have higher first-pass rates. Prune knowledge whose injection correlates with failures.

## PART C — ROUTING THAT ACTUALLY LEARNS (speed × cost × quality per vendor/model)

C1. Clean the reward signal: exclude rate-limited, toolchain-failed, and paused-window outcomes from `bandit.py` rewards (they measure the environment, not the model). Backfill: re-tag historical outcomes accordingly.
C2. One routing decision: merge `bandit.py` + `model_router.py` heuristics + `agentic_coders.py` vendor table into a single `route(task_class, budget, urgency)` with per-task-class posteriors persisted in `fleet_config` (ORCH_ROUTE_*). Task classes: mechanical-batch, feature, refactor, test-fix, docs, self-improvement.
C3. Weekly vendor probe: run a fixed 5-task calibration suite through each available coder lane (subscription Claude, aider/deepseek, gemini), score speed/cost/first-pass, update posteriors. Alert if a lane's quality drops >20%.
C4. Wire `causal_attribution.py` into `eval_harness.py` so routing changes are credited/blamed by outcome deltas, not raw throughput.

## PART D — CONTINUOUS OPTIMIZATION LOOPS (so the operator never has to ask again)

D1. Meta-KPI scoreboard (new table + dashboard card): objective→prompt lead time, prompt→merged lead time, merged/day, first-pass rate, $/merged task, tokens/task, knowledge reuse hit-rate, paused-minutes/day, deploy success rate. Snapshot hourly (extend autopilot snapshots — persist ≥30 days, not hours).
D2. Loop cadence (extend the existing scheduler, don't add a new one):
   - hourly: `generator_feedback` + queue_velocity keep generation matched to execution capacity.
   - nightly: `self_review.py` proposals, BUT with an auto-apply tier — proposals scoring low blast-radius (config/prompt-template/cadence changes, no schema/security surface, per `blast_radius.py`) auto-merge through `eval_harness.py` A/B gating; everything else lands in ONE clustered approval digest.
   - weekly: `meta_loop.py` cross-deploys best loop configs; `prompt_distillation.py` refreshes project briefs; C3 vendor probes; template A/B rotation (keep 1 challenger template per task class live at 10% traffic).
D3. KPI regression watchdog: any auto-applied self-improvement that fails to move its declared KPI within 24h (or regresses any KPI >10%) is auto-reverted with a logged postmortem row. Self-improvement is judged by outcomes, not activity.
D4. Objective intake: a simple `objectives` flow — operator writes one line ("ship X", "cut $/task 30%") via dashboard or `intake/objectives.md`; prompt_factory picks it up. The operator's job shrinks to stating objectives and approving material digests.
D5. Monthly subsystem audit (extend `self_review`): rank all periodic jobs by KPI contribution vs incidents caused; propose disabling the bottom decile (the 277-module sprawl is itself a KPI drag). Deletions are material approvals.

## GUARDRAILS

- All new loops respect the pause-arbiter, drain_mode, meta:product ratio cap, and subscription-only billing. Factory/assembler/knowledge jobs are generators — they must yield to backlog draining.
- Auto-apply tier hard limits: never touches `subscription_guard`, `billing_guard`, `kill_switch`, schema, deploy wiring, or anything `blast_radius.py` scores material. Max 3 auto-applied self-changes/day (`ORCH_SELF_APPLY_DAILY_CAP`).
- Every new module: 20+ tests (normal, edge, failure, pressure), `stats()` + `invalidate()`, env-var config with defaults, fail-soft.
- Ship via intake yourself: after implementing Parts A+B core (A1–A3, B1–B3), decompose Parts C+D into intake DAGs and let the fleet build them — this prompt should be the last serial meta-session.
- Done when: scoreboard live, factory produced ≥1 intake DAG end-to-end (objective → merged → deployed), knowledge quality gate rejecting garbage, one auto-applied self-improvement with measured KPI delta, and a `REPORT-meta-optimizer.md` summarizing all of it.
