# RCA — the P1 queue is not starved, it is dependency-deadlocked

**Found:** 2026-08-26 ~13:05 UTC, by cowork-executor-v6.5 after its second claim
attempt returned 0 rows against a 264-row queue.
**Status:** diagnosis only. No task rows were modified. No dep arrays rewritten.
Remediation requires a human decision — see *Why this was not auto-fixed*.

## The one-sentence version

Every claim query in the fleet treats a dependency as satisfied only when it is
`DONE` or `MERGED`. **262 of 262 claimable-kind QUEUED tasks are blocked by a
dependency that is in some other state — and 209 of those states are terminal,
so they will never become `DONE`/`MERGED`.** The queue can therefore never
drain, no matter how much executor capacity is restored.

## Evidence

Claim predicate, as it appears in the executor playbook:

```sql
NOT EXISTS (
  SELECT 1 FROM unnest(t.deps) AS dep
  WHERE dep NOT IN (
    SELECT t2.slug FROM tasks t2
    WHERE t2.project_id = t.project_id AND t2.state IN ('DONE','MERGED')
  )
)
```

Measured against the live queue at `now() = 2026-08-26 13:0x UTC`:

| | count |
|---|---|
| `tasks` QUEUED, total | 264 |
| ... of kind `speculative` (excluded by design) | 0 |
| ... with **no** deps (immediately claimable) | **0** |
| ... whose deps are all `DONE`/`MERGED` | **0** |
| ... dependency-blocked | **262** |

Zero tasks with an empty `deps` array is itself the tell: a healthy queue always
has some. Every queued row carries exactly one blocking dep edge. Grouped by the
state of that blocking dep:

| blocking dep state | edges | terminal? | can it ever reach DONE/MERGED? |
|---|---:|---|---|
| `DECOMPOSED` | 84 | effectively | no — parent was split into children and is never worked itself |
| `QUEUED` | 53 | no | only transitively, and every one of those is itself blocked |
| `SUPERSEDED` | 50 | **yes** | **never** |
| `QUARANTINED` | 35 | **yes** | **never** |
| `CLOSED` | 28 | **yes** | **never** |
| *row does not exist* | 8 | **yes** | **never** — dangling slug reference |
| `PHANTOM_UNVERIFIED` | 4 | **yes** | **never** |
| **total** | **262** | | |

**209 edges (SUPERSEDED + QUARANTINED + CLOSED + missing + PHANTOM_UNVERIFIED +
DECOMPOSED) are permanently unsatisfiable.** The remaining 53 point at other
QUEUED tasks, all of which are themselves in this set — a closed cycle. There is
no root of the dependency graph that is claimable, which is why the claim CTE
returns 0 rows while reporting a 264-deep backlog.

## What this explains

- **`RUNNING` ≈ 0 for weeks.** Attributed in the escalation chain to the
  executor credit outage (google / openai / xai / deepseek) and the Claude
  weekly-limit reset. Those are real, but they are not the binding constraint:
  with unlimited capacity and the global pause lifted, the claim query still
  returns nothing.
- **p90 queued-task wait climbing monotonically to 1161 h (~48.4 d).** It is not
  a backlog draining slowly. Nothing is draining at all; the p90 rises by
  exactly one hour per hour, which matches the observed 1159.0 → 1160.0 → 1161.1
  progression across the 10:59 / 12:00 / 13:00 UTC runs.
- **Guardrail 8 tripping continuously since 2026-08-10.** "No improvement across
  two consecutive runs" is guaranteed by construction. The guardrail is working;
  it is reporting a real, unchanging deadlock.
- **The oldest blocked tasks being ~48.5 d old.** That is roughly when the
  slice-decomposition batches landed and began referencing sibling slices that
  later went `CLOSED` / `QUARANTINED` / `SUPERSEDED`.

## Related prior work

`fix-null-project-id-tasks-are-permanently-unclaimable` (bugfix, DONE, ~0.7 d
old) is the same *family* of defect — rows unclaimable for a structural rather
than a capacity reason — but a different cause. The cross-project dependency
resolver series (`orch-cross-project-depends-*`, five tasks, all SUPERSEDED
~7.5 d ago) touched this resolver and was abandoned. No open task covers the
DONE/MERGED-only predicate.

## Candidate remediations (for human decision — none applied)

1. **Widen the satisfied-set.** Treat `CLOSED`, `SUPERSEDED`, and `DECOMPOSED`
   as dependency-satisfying alongside `DONE`/`MERGED`. Rationale: each means
   "this work will not be done under this slug," which is a resolution, not a
   pending obligation. Clears ~162 edges. Cheapest fix; changes semantics fleet-wide.
2. **Prune dangling and quarantined edges.** Strip the 8 dep entries pointing at
   non-existent slugs and reconsider the 35 `QUARANTINED` and 4
   `PHANTOM_UNVERIFIED` ones, which represent abandoned work a dependent should
   not wait on. Clears ~47 edges. Requires a `bulk_state_change_audit` row.
3. **Add a deadlock detector to the claim path.** Whatever the policy above,
   the fleet should never again run 48 days without noticing that
   *zero* queued tasks are claimable. A cheap invariant — `claimable == 0 AND
   queued > 0` for N consecutive runs → alert — would have caught this on day one.
4. **Do nothing yet.** Legitimate if the 262 are genuinely dead weight, in which
   case the correct action is bulk-closing them, not unblocking them.

Options 1 and 2 are bulk state changes over 262 rows while `controls.scope =
'global'` has `paused = true`. That is precisely the class of action the pause
exists to prevent an agent from taking unilaterally.

## Why this was not auto-fixed

- Global pause is in force (`paused = true` since 2026-08-24 04:16:43 UTC).
- Guardrail 8 is held; bulk priority/state updates are forbidden while tripped.
- Choosing which states count as "satisfied" is a policy decision about what the
  fleet owes itself, not a mechanical repair. Getting it wrong in the permissive
  direction releases 262 tasks whose premises may be 48 days stale — the exact
  failure mode `ref:sweep` exists to prevent.

## Suggested acceptance

A human picks one of the four options above and records the choice. If option 1
or 2, the predicate change ships as a normal `bugfix` task with a
`bulk_state_change_audit` row covering the dep rewrite. Option 3 should ship
regardless of which of 1/2/4 is chosen.
