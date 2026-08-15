# Client-side scan window — class audit, 2026-08-06

`db.select(table, {"limit": "<big>"})` with no `order` is a single recurring defect, not a
series of unrelated bugs. It has now produced **five** confirmed outage-class failures.
This document records the classification of every large-limit read, what was fixed, and
what is deliberately left alone.

## Why the shape is a bug, not a tuning choice

PostgREST caps a single response at **1,000 rows** regardless of `limit`. So:

- `"limit": "10000"` does not fetch 10,000 rows. It fetches 1,000 and says nothing.
- Without `order`, the 1,000 you get is not the same 1,000 twice, so the defect is both
  silent *and* unreproducible — the worst combination for diagnosis.
- `len(page)` is therefore not a count, and `x in page` is not a membership test.

**Raising a limit is the same bug, later.** The fix is always to classify the read.

## The five confirmed failures

| # | Site | Failure | Status |
|---|------|---------|--------|
| 1 | `merge_train._pick_cards` | scanned newest 3,000 of 238,177 approvals -> months of stranded work | fixed `7ec2d4e` |
| 2 | `merge_train.ensure_integration_card` | 4,000-row client-side scan -> "240 dupes of one slug" (its own comment) | fixed in `done-before-card-is-the-stranding-bug-cowork-20260806` |
| 3 | `ev_scheduler._scored_queue` | arbitrary, unordered 500 of 1,407 QUEUED -> ~907 tasks invisible to EV ordering **and** zero-EV parking | **fixed here** |
| 4 | `config_optimizer` queue depth | `len()` of a 1,000-row page -> autoscaler input structurally incapable of exceeding 1,000 | **fixed here** |
| 5 | `db._done_slugs` | dependency-resolution cache capped at 1,000 of 3,908 completions | **found and fixed here** |

### Finding #5 is new, and it is the throughput answer

The prompt asked whether #3 explains the queue not draining, and required that it be
verified rather than assumed. It is real, but it is not the largest effect. Measured on
prod (`eatfwdzfurujcuwlhdgj`) at audit time:

```
queued            1379
queued_with_deps   462
done_merged       3908      <-- cache could hold at most 1000
running             45
```

`db._done_slugs()` builds the set that answers *"is this task's dependency finished?"* for
every claim decision (`db.py`, `_done_slugs()` consumed in the claim path). It read
`limit: "10000"` and received 1,000. **About 74% of all completions were invisible to
dependency resolution**, so tasks whose dependencies were genuinely satisfied were held as
blocked. With 462 queued tasks carrying deps, this alone strands work indefinitely — and it
degrades as the fleet succeeds more, because `done_merged` only grows.

This is why "tasks queued on 2026-08-02 sat untouched for four days" while newer work moved:
newer tasks are more likely to have their (few, recent) deps inside the 1,000-row window.

## Per-site classification

Taxonomy, per the prompt:

- **COUNT** — needs a real count. Use `db.count()` (server-side `count=exact`).
- **LOOKUP** — needs a specific row. Filter server-side; never scan-and-filter client-side.
- **SAMPLE** — genuinely wants a bounded recent window. Legitimate, but **must** carry a
  deterministic `order`.
- **FULL SCAN** — needs every row. Use `db.select_all()`, which pages to exhaustion.

### Fixed in this change

| Site | Class | Was | Now |
|------|-------|-----|-----|
| `db.py` `_done_slugs()` | FULL SCAN | `limit 10000` (served 1,000), no order | `select_all(..., order="id.asc")` |
| `db.py` claim-path RUNNING mirror sync | FULL SCAN | `limit 2000` (served 1,000), no order | `select_all(..., order="created_at.asc,id.asc")` |
| `ev_scheduler._scored_queue` / `queued_tasks` | FULL SCAN | `limit 500`, **no order at all** | `select_all(..., order="created_at.asc,id.asc")` + `scan_coverage()` |
| `ev_scheduler.load_ctx` economic signals | FULL SCAN | separate `limit 500` window | shares `queued_tasks()` |
| `ev_scheduler.load_ctx` outcome stats | SAMPLE | `limit 5000`, no order | `limit 1000` + `order=created_at.desc` |
| `ev_scheduler.rank_queue` | FULL SCAN | `limit=500` default vs "all QUEUED" docstring | `limit=None` (all) |
| `config_optimizer.suggest_config_changes` | COUNT | `len(select(limit 1000))` | `db.count()` |
| `config_optimizer` before/after throughput (x2) | COUNT | `len(select(limit 1000))` | `db.count()` |

### Item 3 of the prompt: can `db.py` RUNNING truncation corrupt claims?

**Yes — say so plainly.** It does not corrupt the *remote* claim, which is atomic. It
corrupts the **offline fallback**:

1. The read feeds `local_queue.sync_from_remote(queued, running)`.
2. `local_queue` labels each mirror row by the query that produced it, and
   `_reconcile_mirror()` evicts only on TTL or on a non-active state.
3. A genuinely-RUNNING task missing from a truncated RUNNING page keeps whatever mirror
   state it last had. If it was ever seen in a QUEUED page, that stale QUEUED row survives
   for up to `MIRROR_TTL_HOURS`.
4. In DB-down mode the offline path can then hand out a task already RUNNING elsewhere —
   the double-claim the mirror exists to prevent.

It was reachable, not theoretical: `limit 2000` never returned more than 1,000, and on
2026-08-02 the fleet carried 64 zombie RUNNING lanes across machines. Now paged to
exhaustion.

### Live and unfixed — classified, deliberately not blanket-changed

107 `SCAN_WINDOW_NO_ORDER` sites remain. The lint rule reports them at **warning** severity
precisely so this backlog is visible without turning one audit into a fleet-wide rewrite.
The highest-consequence ones, classified:

| Site | Class | Consequence of truncation |
|------|-------|---------------------------|
| `committees.py:1690` `kg_edges` `have` set | LOOKUP (dedupe) | Same shape as failure #2. A truncated `have` set means duplicate `kg_edges` inserts. |
| `config_approval.py:78` `_seen_fingerprints` | LOOKUP (dedupe) | Already-decided config entries get re-assessed -> duplicate approvals. |
| `dag_validator.py:108` `existing_slugs` | LOOKUP | Slug-existence check answers "absent" for a slug that exists. |
| `cx_reviewer_queue.py:13-14` override rate | COUNT | Ratio of two independently-clamped `len()`s; meaningless above 1,000 either side. |
| `experiment_analyzer.py:150` total/active | COUNT | Experiment totals clamp at 500. |
| `agentic_coders.py:422` RUNNING lanes | COUNT | `limit 120` against a 66-lane-per-machine fleet; close to the edge already. |
| `committees.py:1259,1288` calibration backtests | SAMPLE | Seat/committee weights fit to a non-reproducible sample. |
| `adversarial_fleet.py:232` compliance receipts | SAMPLE | Coverage aggregated over an arbitrary window. |
| `demand_mining.py:23` requests corpus | FULL SCAN | Demand mining silently ignores most of the corpus. |
| `fleet_doctor.py:106` projects | FULL SCAN | Benign today (projects table is ~10 rows), still the wrong shape. |

Ordering these by consequence: the LOOKUP/dedupe sites are next, because they produce
*wrong writes* (duplicates) rather than merely incomplete reads.

### The documented exception — do not "fix" it

`fleet_stuck_alarm.py:57-58`

```python
queued = len(db.select("tasks", {"select": "id", "state": "eq.QUEUED", "limit": "5001"}) or [])
```

`5001` is a deliberate **"is there more than 5000?"** probe. `len()` of that page *is* the
answer it wants, and it never needs the rows. This is a legitimate idiom. The linter exempts
it via `SENTINEL_LIMITS = {5001}` in `tools/convention_lint.py`, and a test
(`test_real_sentinel_site_is_clean`) fails if a future change starts flagging it.

## New tooling

### `db.select_all(table, params, order=...)`

Pages a filtered select to exhaustion. Notes:

- A deterministic `order` is mandatory — offset paging over an unordered relation can
  repeat and skip rows between pages. Callers passing none get `id.asc`.
- `SELECT_ALL_MAX_ROWS` (default 200,000, env `ORCH_SELECT_ALL_MAX_ROWS`) is a hard stop so
  a FULL SCAN of a runaway table cannot become its own outage inside a 900s loop. Hitting
  it **prints** — a truncated result is never returned silently, which is the whole point.

### `SCAN_WINDOW_NO_ORDER` lint rule

In `tools/convention_lint.py`. Flags `select(..., {"limit": N})` where `N >= 100` and there
is no `"order"` key. Recognises `"500"`, `500`, and `str(500)`. `select_all` is never
flagged. Severity `warning`, so it surfaces the 107-site backlog without failing CI.

`# noqa: SCAN_WINDOW_NO_ORDER` now works. `CONVENTION_LINT.md` has documented `# noqa` since
Phase 1 but nothing implemented it, so the documented escape hatch silently did nothing;
`_apply_noqa()` implements it for all rules.

## Non-goals honoured

No limit was raised, and nothing was made unbounded without pagination. A full unpaginated
scan of a 238k-row table inside a 900s loop is its own outage — hence `SELECT_ALL_MAX_ROWS`
and the loud truncation report. Correctness here means *the query answers the question
asked*, not *the number is bigger*.

## Tests

`runner/tests/test_scan_window_correctness.py` — 20 cases. The fake db **enforces the
1,000-row response cap**; a fake that happily returned 5,000 rows for `limit: "5000"` would
let every one of these bugs pass its own test.

1. `ev_scheduler` scores all 1,500 QUEUED tasks, deterministically ordered, reproducibly,
   with no duplicate rows across pages; `scan_coverage()` reports a short scan against true
   depth.
2. `config_optimizer` reports 1,407 and 10,000 — above the page cap.
3. A LOOKUP finds its target with 10,000 newer rows present, and the truncated-scan version
   is shown missing it.
4. The lint rule flags `limit>=100` without `order` (incl. `str(500)`), passes with `order`,
   passes small limits, passes `select_all`, and honours `# noqa`.
5. The `5001` sentinel is not flagged, and the real `fleet_stuck_alarm.py` is clean.
6. `db._done_slugs()` sees all 3,908 completions (finding #5).
7. Regression guard: `ev_scheduler.py` and `config_optimizer.py` must not reacquire the
   shape.

## MATERIAL

Changes scheduling, dependency resolution, and autoscaling inputs fleet-wide. Lands for
human review.

Audited and specified by Claude in a Cowork session, 2026-08-06, after the same
anti-pattern produced its third and fourth confirmed failure in one day; the fifth was
found during this audit.
