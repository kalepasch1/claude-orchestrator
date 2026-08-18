# Wave C, slice 2 — reusable project helpers for the codegen platform spine

Task: `dropbox-wave-c-compounding-codegen-platform-spine--slice-2-reuse-project-helpers`.

> "Review existing project helpers (utility functions, common patterns) that align with the
> intent of this patch template. Identify at least three reusable helpers and explain how they
> can be leveraged to simplify or enhance the implementation. **Do not modify any code.**"

This document is the whole deliverable. No source file is touched — the survey is the point,
and this fleet's recorded failure mode is shipping a second implementation of something it
already owns. Verified against `origin/master` @ `59de85f2`.

---

## 1. `runner/db.py` — the paged, truncation-aware data access layer

**Reuse instead of:** any hand-rolled PostgREST call, and in particular any `db.select(...)`
with a large `"limit"`.

**Why it matters more than it looks.** `db.py` carries a comment block naming **four
outage-class failures** all caused by the same mistake — assuming `select` returns everything:

> `merge_train._pick_cards` scanning 3,000 of 238,177 approvals; `ensure_integration_card`
> producing 240 duplicates of one slug; `ev_scheduler` scoring an arbitrary 500 of 1,407 QUEUED
> tasks; `config_optimizer` autoscaling off a queue depth structurally incapable of…

PostgREST caps a single response at 1,000 rows regardless of `limit`, so a bare
`{"limit": "5000"}` does not widen the window — **it hides the truncation.**

**How the spine leverages it**

| Need | Use | Not |
|---|---|---|
| bounded read | `db.select(table, params)` | raw `requests` to `/rest/v1/...` |
| full scan | `db.select_all(table, params, page_size=..., max_rows=..., order=...)` | `select` with a big `limit` |
| "how many" | `db.count(table, params)` | `len(db.select(...))` |
| health branch | `db.is_db_down()` | catching exceptions per call site |
| logging a payload | `db.redact_secrets(text)` | printing the row |

Any spine component that reports pipeline state is a scanner by nature, so it must use
`select_all` + `count`, and `_warn_if_truncated` gives it a free alarm if it regresses.

---

## 2. `runner/branch_lease.py` — sole-writer leasing, already fail-closed

**Reuse instead of:** a spine-local "is anyone else building this branch" check.

**Why it matters.** Every spine stage that writes to an `agent/*` branch is a concurrent writer,
and this fleet runs 16 executors. `branch_lease` already solves it against a DB RPC with a
heartbeat and a TTL:

```
acquire(task, repo, branch, base, owner=..., ttl=...) -> lease | None
heartbeat(task_id, branch) -> bool
release(task_id, branch)   -> bool
active(task_id, branch)    -> lease | None
```

The load-bearing detail is the **direction** of its failure. `acquire` fails **CLOSED**:

> "An unavailable lease control plane is not proof of contention. Fail closed and let the
> runner requeue instead of turning an RPC outage into a task error."

while `heartbeat` fails **soft (ALIVE)**. That asymmetry is deliberate and is exactly the kind of
thing a re-implementation gets backwards — a spine that failed *open* on acquire would let two
writers onto one branch during an RPC blip. Reuse the module; do not copy the pattern.

**Caveat worth carrying:** CLAUDE.md flags a bare `91`-second staleness literal in this file as
a magic number that should be lifted to an `ORCH_`-prefixed env var so it is fleet-pushable via
`fleet_control.py`. Anything the spine adds here should be `ORCH_`-prefixed from the start.

---

## 3. `runner/resource_governor.py` — the memory/disk admission gate

**Reuse instead of:** letting spine stages start work whenever they are asked to.

```
can_claim(n_active) -> (ok: bool, reason: str)
lane_target(free_gb=None, ceiling=None)
disk_pct(path) -> (used_pct, free_gb)
```

`can_claim` is the **pre-flight** gate the runner calls before each task, covering the gaps
between the slower periodic `govern()` ticks. It returns a *reason string*, not just a bool, so a
refusal is loggable rather than mysterious. The distilled convention in CLAUDE.md is explicit
that resource expansion should be gated on `resource_governor.can_claim()` "to prevent wedging
under pressure" — a spine that spawns per-stage workers is exactly such an expansion.

Note it is currently short-circuited by `ORCH_DISABLE_MEM_GATE` (set after the RAM gate blocked
6,622 queued tasks on a 48 GB machine). Call it anyway: the flag is the operator's lever, and
routing through the helper is what makes the lever work fleet-wide.

---

## Two more the spine will want

### 4. `runner/patch_templates.py` — reuse-before-rebuild, and its registry

`build(task)`, `lookup(template_id)`, `pre_claim_hook(task)`, with a fail-soft JSONL fallback at
`.runtime/patch_templates.jsonl` when the `knowledge` table is unavailable. `lookup` returns `{}`
on any miss or error and never raises. `runner/tests/PATCH_TEMPLATE_REGISTRY.md` maps each
template hash to its owner module and acceptance test, and the convention is to add a row **in
the same commit** as a new hash-scoped test. Spine codegen that emits reusable patches should
register through this, not alongside it.

### 5. `runner/merged_diff_library.py` — proven-diff retrieval

`features()`, `intent_signature()`, `acceptance_intent()`, `adapter_template()`, `record()`,
`find(task, limit)`. This is the "adapt a proven prior diff before drafting net-new code"
machinery the task prompts themselves invoke via `PATCH TRANSPLANT` / `REUSE FIRST` markers.
A codegen spine that does not call `find()` before generating is, by construction, the
duplicate-work problem it exists to solve.

---

## Cross-cutting conventions these helpers encode

1. **Fail-soft, but logged.** Return a sensible default (`""`, `[]`, `{}`, `False`) rather than
   raising. A broad `except` must write a diagnostic first — a silent `except Exception: pass`
   is the defect, a logged one is the convention.
2. **Direction of failure is a design decision.** `branch_lease.acquire` fails closed;
   `heartbeat` fails soft. Choose per call site and say why in a comment.
3. **Module-level singleton.** Public module functions delegate to one thread-safe instance
   (`acquire()` → `_pool.acquire()`), so callers never thread state through.
4. **`ORCH_`-prefixed env vars for every tunable**, so `fleet_control.py` can push them
   fleet-wide. No bare literals.
5. **Never trust an unpaged read.** See §1.

## Recommendation for the sibling slices

Before the spine adds a scanner, a lock, a worker pool, a template store or a diff cache, check
this list first. On the current evidence the spine needs **no new** data-access, locking or
admission primitives — only composition of the five above.

*Analysis only; no code modified, per the task's explicit instruction.*
