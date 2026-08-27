# The executor queue is deadlocked, not empty

**Date:** 2026-08-25
**Found by:** cowork-executor scheduled run
**Status:** diagnosed, not fixed — the fix needs an operator decision (see "Why I stopped")

> **Update 2026-08-27** (cowork-executor-3 scheduled run). Steps 1–3 of "Suggested
> order of work" have landed in the runner: `runner/db.py` now pages `_done_slugs()`
> to exhaustion, counts `DEPLOYED_AND_VERIFIED`, resolves qualified `project:slug`
> deps, and reports `why_no_claim()`; `runner/queue_deadlock_report.py` names the
> unclaimable tasks by category. **The sixteen `cowork-skills/*.SKILL.md` files were
> not updated with them** — they carry a third copy of the claim predicate, so every
> scheduled executor still ran the pre-fix query and still mapped 0 rows to "queue
> empty". That copy is corrected on branch
> `agent/fix-cowork-executor-false-success-signal`, with
> `runner/tests/test_cowork_skill_claim_parity.py` pinning all three properties so the
> three copies cannot drift apart again silently.
>
> Measured after the correction: **1** of 137 QUEUED tasks becomes claimable. As
> predicted above, these are correctness fixes and not the remedy. **Step 4 — triaging
> the childless `DECOMPOSED` parents — is still the bulk of the deadlock and still
> needs a human.** Current split: 102 of 137 unclaimable — 14 decomposed-childless,
> 12 collapsed (redirectable; only 1 points at a `DONE` target), 76 terminal.
>
> **New, and more urgent than the deadlock: the executor skills never checked the kill
> switch.** `runner/db.py` drops paused projects from its claim set and
> `kill_switch.is_paused()` gates the runner on the global and host scopes, but none of
> the sixteen `SKILL.md` files mentioned `controls` or `paused` at all. Meanwhile a
> `scope=global` pause has been in force since 2026-08-24 ("every hosted provider is out
> of credit"), and **all sixteen portfolio projects carry their own project-scope pause**
> — `tomorrow`'s set by the operator by name, `apparently`/`smarter`/`apparently-law`
> since 2026-08-09, and nine more from a "controlled fleet verification" that declared
> itself REVERSIBLE and auto-lifting and then never lifted. Nothing in the skill would
> have stopped a scheduled executor from committing and pushing through all of it. A
> Step 0c gate is on the same branch. Note the interaction: the dependency deadlock is
> the only reason this has not already caused pushes against a halted fleet.
>
> **The `fleet_config` heartbeat guard has not changed**, and section 4 below overstates
> one detail — correcting it here rather than editing the original.
> `enforce_compiled_fleet_config()` still requires an authorized `policy_change_id` for
> every key; a Step 4 heartbeat write attempted this run was rejected with the same
> `P0001`. But `COWORK_EXECUTOR_V6_LAST_RUN` **does exist** — section 4's "has never once
> landed" is wrong. It is *frozen*, last written 2026-08-05 22:51 UTC, which is also the
> newest surviving executor heartbeat of any kind (not `COWORK_EXECUTOR_12` at
> 2026-07-15, as section 4 states). The conclusion is unchanged and the date is worse
> than it looks: telemetry stopped when the guard landed, and every run since has been
> invisible. Worth stating precisely in a document about false signals.
>
> **Also found this run: BLOCKED is not a resting state.** Four tasks marked BLOCKED
> here at 12:56 UTC, each with a note naming exactly what was missing, were re-claimed
> by a *different, concurrently running* cowork executor
> (`cowork-executor-v6-1787835696`) at 13:01:36 — thirteen minutes later — which
> overwrote all four notes with `agentic-repair:rework`. So an executor's diagnosis of
> why a task cannot proceed survives about as long as it takes the next executor to
> start, and the repair loop recycles the task regardless of what the note said. This is
> a large part of why the same slugs keep reappearing: nothing downstream reads the
> BLOCKED reason. Any triage of the 102 unclaimable tasks will be undone the same way
> unless the rework path is taught to respect an executor's BLOCKED note.

## Summary

327 tasks sit in `QUEUED`. The executor's atomic-claim CTE returns **0 rows**. Every
executor run therefore hits the skill's exit condition — "If 0 rows → queue empty,
write `<run-summary>`, stop" — and exits reporting success.

The queue is not empty. It is deadlocked, and has been since at least **2026-07-15**.
251 of the 327 tasks have been stuck for more than 7 days.

Every task in the queue is excluded by one clause of the claim query: the dependency
filter. All 327 have a non-empty `deps` array, and of 333 dependency edges only **3**
resolve to a `DONE`/`MERGED` task.

## The claim query cannot distinguish "blocked" from "empty"

This is the load-bearing failure. A dependency-starved queue and a finished queue
produce the identical signal — zero rows — and the skill maps that signal to "work
complete." Sixteen executors have been reporting clean runs against a queue that has
not moved in six weeks.

Whatever else is fixed, the claim step should report *why* it got nothing: count
`QUEUED` separately from claimable, and treat `queued > 0 AND claimable = 0` as an
alert, never as an exit.

## Where the 333 dependency edges point

| blocker state | edges | queued tasks blocked | will it ever satisfy? |
|---|---:|---:|---|
| `DECOMPOSED` | 111 | 110 | no — terminal |
| `QUEUED` | 72 | 72 | only transitively, and nothing is claimable |
| `SUPERSEDED` | 64 | 64 | no — terminal |
| `QUARANTINED` | 37 | 37 | no — terminal |
| `CLOSED` | 28 | 28 | no — terminal |
| *slug does not exist* | 14 | 13 | no — unsatisfiable by construction |
| `PHANTOM_UNVERIFIED` | 4 | 4 | no — terminal |
| `DONE` / `MERGED` | 3 | 3 | satisfied |

The dependency predicate only accepts `DONE` and `MERGED`. Roughly 254 tasks are
blocked by a state that is terminal and can never transition into that pair. The 72
blocked-by-`QUEUED` are downstream of those same dead blockers.

## By project

| project | queued & blocked | missing slug | by DECOMPOSED | by dead states | by QUEUED |
|---|---:|---:|---:|---:|---:|
| beethoven | 193 | 8 | 57 | 93 | 35 |
| tomorrow | 41 | 1 | 18 | 10 | 12 |
| sustainable-barks | 25 | 0 | 12 | 6 | 7 |
| kalepasch-com | 15 | 0 | 7 | 6 | 2 |
| santas-secret-workshop | 15 | 0 | 2 | 6 | 7 |
| darwn | 14 | 1 | 2 | 5 | 6 |
| pareto-2080 | 13 | 2 | 5 | 4 | 3 |
| smarter | 5 | 0 | 5 | 0 | 0 |
| apparently | 4 | 1 | 0 | 3 | 0 |
| racefeed | 1 | 0 | 1 | 0 | 0 |
| prediction-markets-institute | 1 | 0 | 1 | 0 | 0 |

## Three distinct root causes

### 1. `DECOMPOSED` parents that were never actually decomposed

58 distinct `DECOMPOSED` tasks act as blockers. Checked against **both** the
`-slice-%` naming convention and the authoritative `parent_task_id` column:

- **51 of 58 have zero children.** No slices, no rows pointing back at them.
- 7 have children; **all 7 still have open children**.
- **0 have a fully completed child set.**

So the obvious one-line fix — add `DECOMPOSED` to the satisfied-states allowlist — is
**wrong**. For 51 of these the work was marked as split up and then no children were
ever created. The task evaporated. Unblocking their dependents would launch work whose
stated prerequisite never happened, against premises nobody validated.

These 51 need to be re-decomposed or re-queued as real work, not waved through.

### 2. Truncated slice chains

Ten of the fourteen unsatisfiable edges are a slice depending on its immediate
predecessor, where the predecessor row does not exist at all:

```
beethoven   dropbox-operator-gate-amendment-auto-ship-authoriz-slice-2  → …-slice-1
beethoven   improve-automated-task-state-transition-reproduce--slice-2  → …-slice-1
beethoven   improve-enhance-automated-testing-and-integratio-slice-5    → …-slice-4
beethoven   improve-implement-advanced-branch-management-recon-slice-4  → …-slice-3
beethoven   improve-implement-advanced-task-prioritization-slice-5      → …-slice-4
beethoven   improve-implement-automated-testing-framework-slice-3       → …-slice-2
beethoven   improve-implement-real-time-configuration-manage-slice-5    → …-slice-4
beethoven   improve-streamlined-branch-management-with-autom-slice-4    → …-slice-3
darwn       backlog-batch-darwn-8585b60-adapt-proven-prior-dif-slice-4  → …-slice-3
tomorrow    dropbox-tomorrow-apparently-pareto-bridges-perpetu-slice-5  → …-slice-4
apparently  dropbox-v5-…-ap-6-live-reg-ap6a-portal-recon                → …-ap-6-live-reg-contracts
```

Same shape as cause 1: the decomposer wrote slice N without ever writing slice N−1.
Worth checking whether the decomposer is dropping rows on insert or losing them to a
later purge, since both failure modes are still live.

### 3. Cross-project dependencies can never resolve

`pareto-2080` has two tasks depending on beethoven work using a qualified
`project:slug` form:

```
adopt-shared-development-terminal-in-pareto
  → beethoven:shared-development-terminal-sdk-and-madeus-client

contracts-pareto-development-session-embed
  → beethoven:shared-development-terminal-sdk-and-madeus-client
  → beethoven:foulkon-illuminati-apparently-steering-hooks
```

The resolver only ever looks within the same project:

```sql
WHERE t2.project_id = t.project_id AND t2.slug = dep
```

A dep carrying a `beethoven:` prefix cannot match a slug in `pareto-2080` — and would
not match even unprefixed, because the row lives in another project. **Cross-project
deps are unsatisfiable by construction.** This is a plain resolver bug: it needs to
split on `:` and look the slug up in the named project.

Both referenced beethoven tasks do exist, and both are themselves `QUEUED` and stuck —
so fixing the resolver alone will not free them.

### 4. The heartbeat has been silently failing, which is why nobody noticed

Step 4 of the executor skill writes `COWORK_EXECUTOR_V6_LAST_RUN` to `fleet_config`.
That write is rejected:

```
ERROR: P0001: fleet_config writes require an authorized policy change
CONTEXT: PL/pgSQL function enforce_compiled_fleet_config() line 4
```

The guard added after the 2026-08-02 plaintext-credential incident covers the whole
table, not just credential keys. Consequences:

- `COWORK_EXECUTOR_V6_LAST_RUN` **does not exist**. The v6 heartbeat has never once
  landed.
- The newest surviving heartbeat of any executor is `COWORK_EXECUTOR_12_LAST_RUN` at
  **2026-07-15**, which is exactly when the queue stopped moving.

So the fleet has no telemetry: executors cannot report that they did nothing, and the
last thing the dashboard saw was a healthy run six weeks ago. Either exempt the
heartbeat keys from `enforce_compiled_fleet_config()` or move run telemetry to its own
table.

Two of the older heartbeats are also worth reading — `COWORK_EXECUTOR_10` and
`COWORK_EXECUTOR_7` both recorded *"9 others skipped: too complex, sensitive/secret,
vague, or legal gate"*. The current skill responds to that history with a blanket
"ZERO SKIP — sensitivity, vagueness, secrets are not skip reasons" rule. That rule
does not fix the underlying problem, and it instructs executors to push code for tasks
they have flagged as sensitive or not understood. Worth revisiting alongside the rest:
the earlier runs were right to stop, they were just bad at saying why.

## Why I stopped rather than unblocking the queue

The executor skill instructs me to loop until the queue drains and forbids stopping
early. I stopped anyway, because draining this queue means mutating the fleet's control
plane in ways the skill does not authorize and that I do not think should happen
unreviewed:

- **The one-line fix is wrong.** Adding `DECOMPOSED` to the allowlist would unblock 110
  tasks, 51 of whose prerequisites were never built. This repo's own `CLAUDE.md` is
  emphatic that building something whose premise is stale is the most expensive failure
  the fleet has. Bulk-clearing deps would cause exactly that, several dozen times over.
- **The three causes need different remedies.** Missing slices need regeneration;
  cross-project deps need a resolver change in the claim SQL; empty decompositions need
  a judgment call on whether the parent work is still wanted at all.
- **"Which states count as satisfied" is a design decision.** `DECOMPOSED`,
  `SUPERSEDED` and `DEPLOYED_AND_VERIFIED` each have a defensible claim to counting as
  satisfied, and each answer releases a different set of tasks. That is yours to make.

No task states were modified. No branches were pushed. The claim attempt took zero rows
and mutated nothing. The one write I attempted — the Step 4 heartbeat — was rejected by
the `fleet_config` guard, so this file is the only durable record of the run.

## Suggested order of work

1. **Stop the false-success signal first.** Make the claim step distinguish `queued=0`
   from `claimable=0`, and alert on the second. Until this lands, every fix is invisible
   and every regression re-hides itself.
2. **Fix the cross-project dep resolver** — smallest, unambiguous, correctness-only.
3. **Decide the satisfied-state allowlist**, most likely adding
   `DEPLOYED_AND_VERIFIED`, which is strictly stronger than `DONE` and is currently
   treated as a blocker.
4. **Triage the 51 childless `DECOMPOSED` parents** individually — re-decompose, re-queue,
   or close along with their dependents. This is the bulk of the deadlock and the part
   that most needs a human.
5. **Regenerate or retire the 11 truncated slice chains**, and find out why the
   decomposer dropped them.

## Reproducing these numbers

Every figure above came from read-only queries against project `eatfwdzfurujcuwlhdgj`.
The core one:

```sql
WITH q AS (
  SELECT t.id, t.project_id, unnest(t.deps) AS dep
  FROM tasks t WHERE t.state='QUEUED'
)
SELECT COALESCE(d.state::text,'<no such task slug>') AS blocker_state,
       count(*) AS edges, count(DISTINCT q.id) AS queued_tasks_blocked
FROM q
LEFT JOIN LATERAL (
  SELECT t2.state FROM tasks t2
  WHERE t2.project_id = q.project_id AND t2.slug = q.dep
  ORDER BY CASE WHEN t2.state IN ('DONE','MERGED') THEN 0 ELSE 1 END LIMIT 1
) d ON true
GROUP BY 1 ORDER BY 2 DESC;
```
