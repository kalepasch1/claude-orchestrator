# Cowork → Orchestrator Staging Process

**Purpose.** A single, replicable channel by which any Cowork session turns analysis into governed, autonomous building. Cowork **stages** work; the Mac runner **executes** it in isolated worktrees under cost caps, tests, and approval cards. No Cowork session runs Claude Code itself, hand-rolls a worktree, or spends — it only enqueues well-formed tasks into the one control plane you already built.

This resolves every "give me a worktree / stage this" request: you never make a worktree by hand again. You stage a task; the runner creates `{repo}-wt/{slug}` for it automatically (`setup-worktrees.sh`).

## The one-screen model

```
Cowork session  ──stages──►  Supabase `tasks` (QUEUED)  ──polled by──►  Mac runner
   (analysis,                  cowork_stage.py              claim_task()      │
    backlog.json)              (idempotent, dry-run                           ▼
                                by default)                          {repo}-wt/{slug} worktree
                                                                     Claude Code builds + tests
   web dashboard  ◄──realtime── approvals / outcomes / cost ◄────────  confidence gate + PR
   (you approve material changes, watch $ + tests)
```

Everything inside the runner is already governed: `$40/day · $10/hr · 80 calls/hr` caps, the kill switch, the waste guard (pauses a project that spends >$5/6h shipping nothing), `confidence.py` gating merges, and per-task `outcomes` telemetry feeding the bandit/self-improvement loop. Staging adds rows; it changes none of those guarantees.

## How to stage (any Cowork session)

1. **Write/extend the backlog** at `cowork-backlog/backlog.json`:
   - `projects`: `name → { repo_path (absolute, on the Mac), default_base }`.
   - `tasks[]`: each `{ project, slug, prompt, deps, kind, base_branch?, model? }`.
   - **Contract-first (enforced):** the first task of each project must be `contracts-*` with `deps: []`; it pins shared interface files so parallel branches can't disagree on boundaries. Everything else depends on it (directly or transitively).
   - **Prompt rule (from `planner.py`):** each `prompt` is *self-contained* and includes an explicit **file scope** and an **acceptance test to run**. Tasks touching the same files must be chained via `deps`; tasks touching different files must not, so they run in parallel.
   - `kind ∈ {build, research, efficiency, self, legal, gtm, bugfix, refactor, batch}`.

2. **Dry-run (default, no writes):**
   ```bash
   python3 runner/cowork_stage.py --backlog cowork-backlog/backlog.json
   ```
   Validates the DAG (deps resolve, no cycles, contract-first) and prints exactly what would be enqueued.

3. **Commit (on the runner Mac, with `SUPABASE_SERVICE_KEY` set):**
   ```bash
   python3 runner/cowork_stage.py --backlog cowork-backlog/backlog.json --commit
   # or one project: --project tomorrow --commit
   ```
   Idempotent: a `(project, slug)` already present in a non-terminal state is skipped, so re-staging never duplicates.

4. **Activate the runner** (only when you want it to actually build — it stays paused otherwise; see `ACTIVATION.md`): log in the failover account, restart `runner.py` so it picks up the spend-capped code, then lift the kill switch. Staged tasks sit harmless in `QUEUED` until then.

5. **Monitor / QA / approve** from the web dashboard: material changes surface as `approvals` cards (with why/value/risk/alternatives); you approve from anywhere; `outcomes` shows tests + cost per task. Failed tasks land in `FAILED/TESTFAIL/BLOCKED` with a log tail for re-scoping.

## Replicability — how to channel future sessions

Tell any future Cowork session: *"Stage your work through the orchestrator: add tasks to `cowork-backlog/backlog.json` (contract-first, file-scoped prompts with acceptance tests) and dry-run `runner/cowork_stage.py`. Do not build directly."* That single instruction makes every session additive to the same governed queue, monitored on the same dashboard, QA'd by the same confidence gate, and improved by the same outcomes loop. The backlog file is the durable, versioned interface between Cowork's planning and the runner's execution.

## Cross-app ordering (manual, because runner deps are per-project)

`claim_task` resolves `deps` within a project. Cross-app sequencing is encoded by **kind + the contract tasks**: land each project's `contracts-*` first (they're independent and run in parallel), then the Tomorrow hub features, then the Smarter/Apparently bridge tasks that consume Tomorrow's pinned contracts. The bridges already exist on both sides (Smarter `warroom/bridge.post.ts`; Apparently rewards/gaming S2S), so those tasks are completion/activation, not greenfield.

## What stays a human gate (by design)

Unpausing the runner, approving material-change cards, and **executing the legal documents** (the contingent-identity structure is staged as a `legal` task that produces drafts for counsel execution — default-OFF, ECP-only). The orchestrator builds and tests; it never lifts its own pause, merges past the confidence gate, or signs anything.
