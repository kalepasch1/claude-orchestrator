# Orchestrator Improvement Plan — Full-Throttle Weekend & Beyond

*Generated 2026-07-11 from a full codebase audit of runner/, tests/, and supporting infrastructure.*

---

## Executive Summary

The orchestrator is architecturally sound — fail-soft error handling, serialized merge train, adaptive model routing, and fleet-wide config via Supabase are all strong foundations. But the audit uncovered **5 systemic categories** of improvement that, taken together, would dramatically increase throughput, reduce error/retry waste, and improve code quality:

1. **Observability is blind** — bare `print()` everywhere, no structured logging, no metrics, no timing on hooks
2. **Silent error swallowing** — 40+ `except Exception: pass` blocks make debugging nearly impossible
3. **Serial bottlenecks in the hot path** — pre-hooks and post-hooks run sequentially when most are independent
4. **Test coverage at 18%** — 52 of 284 source files have tests; critical systems like `slo_controller.py` have zero
5. **No CI/CD pipeline** — `lefthook.yml` is entirely commented out; quality gates exist only inside the orchestrator's own merge train

---

## Tier 1 — High Impact, Ship This Weekend

These are changes the fleet can self-execute from the backlog. Each is a single-file fix with clear proof criteria.

### 1.1 Structured Logging (replace bare `print()`)

**Problem:** Every file uses `print()`. No log levels, no timestamps, no correlation IDs linking a task through claim → dispatch → hooks → completion. When something goes wrong, you grep terminal scrollback.

**Fix:** Add a lightweight `log.py` module:
```python
# runner/log.py
import logging, os, socket
fmt = f"%(asctime)s [{socket.gethostname()}] %(levelname)s %(name)s | %(message)s"
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format=fmt)
def get(name): return logging.getLogger(name)
```
Then replace `print(f"[tag] ...")` with `log.info(...)` in each module. Add a `task_id=` field to the formatter for correlation.

**Proof:** `grep -r 'print(' runner/*.py | wc -l` drops to near-zero; log output includes timestamps and levels.

**Impact:** Every debugging session gets 10x faster. Fleet-wide log aggregation becomes possible.

### 1.2 Surface Swallowed Errors (the `except: pass` audit)

**Problem:** `runner.py` has 40+ blocks like:
```python
try:
    result = some_hook(task)
except Exception:
    pass  # fail-soft
```
The fail-soft philosophy is correct — hooks should never wedge the runner. But *silent* failure means you can't tell which hooks are broken, how often they fail, or what errors they throw.

**Fix:** Replace `pass` with `log.debug(f"hook {name} failed: {e}")` and increment a counter. Don't change the control flow — still swallow and continue.

**Files:** `runner.py` (lines 527–902 pre-hooks, lines 1400–1544 post-hooks), `resource_governor.py` (line 69), `merge_cycle.py` (line 91), `slo_controller.py` (lines 92–133).

**Proof:** A test asserting that a failing hook logs but doesn't raise.

### 1.3 Parallelize Pre-Hook Pipeline

**Problem:** `runner.py` lines 680–902 run 15+ enrichment hooks **serially**: context_pack → precedent → smart_compress → cade_tournaments → model_slashing → output_recycling → adaptive_budget → transfer_learning → prompt_distillation → debate_compress → cross_project_templates → session_cache → prompt_bankruptcy → multi_agent_pipeline → live_bidding. Most are independent.

**Fix:** Group hooks into dependency tiers and run each tier with `concurrent.futures.ThreadPoolExecutor`. The `parallel_gates` pattern (already used for verify/judge/confidence) is the template:

```python
# Tier 1: independent enrichment (run in parallel)
with ThreadPoolExecutor(max_workers=4) as pool:
    futures = {
        pool.submit(context_pack, task): "context_pack",
        pool.submit(precedent, task): "precedent",
        pool.submit(smart_compress, task): "smart_compress",
        ...
    }
    for f in as_completed(futures):
        try: results[futures[f]] = f.result()
        except Exception as e: log.debug(f"{futures[f]}: {e}")

# Tier 2: hooks that depend on Tier 1 results (serial or smaller parallel group)
```

**Impact:** If the average hook takes 200ms and there are 15 hooks, serial = 3s, parallel (4 workers) ≈ 0.8s. Over 25 concurrent tasks, that's **55s saved per claim cycle**.

### 1.4 Fix the `claim_task` N+1 Query Pattern

**Problem:** `db.py` `claim_task()` makes 4+ DB round trips per claim cycle: fetch up to 1000 QUEUED tasks, fetch projects, fetch running tasks, fetch last-activity. Plus `done = {t["slug"] for t in select("tasks", ...)}` fetches ALL completed slugs with no LIMIT — unbounded as the task table grows.

**Fix:**
- Add `limit=5000` to the done-slug query (or better: use a DB-side `NOT EXISTS` subquery via PostgREST RPC)
- Cache the `done` set for 60s (it changes slowly)
- Combine the projects/running/last-activity queries into a single RPC or batch them

**Proof:** Measure claim cycle latency before/after; target < 500ms per cycle.

### 1.5 SLO Controller Fail-Safe Inversion

**Problem:** `slo_controller.py` returns `{"ok": True}` on any exception (lines 92–133). A DB outage makes all SLOs appear GREEN. This is fail-*unsafe* — it should be fail-*unknown*.

**Fix:** Return `{"ok": None, "state": "UNKNOWN", "reason": str(e)}` on exception. Display as YELLOW in dashboards. Don't trigger automated remediation on UNKNOWN (avoid thrashing), but do surface the measurement failure.

**Proof:** A test that mocks a DB failure and asserts the SLO returns UNKNOWN, not GREEN.

---

## Tier 2 — Medium Impact, Queue for Next Week

### 2.1 Thread-Safety Audit (GIL-dependent globals)

**Problem:** Multiple global mutable dicts are accessed from threads with no locks:
- `runner.py`: `_projects` (line 136), `_PERIODIC_PIDS` (line 1975), `_qdepth` (line 1844)
- `fleet_control.py`: `_last_pull` (line 29)
- `resource_governor.py`: `THROTTLE_FILE` read/write (lines 389–398)

These work under CPython's GIL but are technically unsafe and will break under free-threaded Python (PEP 703, coming in 3.14).

**Fix:** Add `threading.Lock()` to each shared mutable. Minimize critical sections — do I/O outside the lock.

### 2.2 Task Slicer Atomicity

**Problem:** `task_slicer.py` flips the parent to DECOMPOSED (line 163) *before* inserting child slices (line 181). If the runner crashes between these operations, the parent is DECOMPOSED with no children — orphaned forever.

**Fix:** Insert children first, then flip parent. Or use a transaction wrapper if PostgREST supports it (via RPC).

### 2.3 Intake Watcher — Unbounded Retry on Bad Files

**Problem:** A permanently-malformed `PROMPT-*.md` file will be retried every tick forever with no backoff or max-retry counter (line 157–160). This burns model calls on planner decomposition attempts.

**Fix:** Track retry count per file (in-memory dict keyed by path). After 3 failures, move to `intake/failed/` and emit an approval card for human review.

### 2.4 `datetime.utcnow()` Deprecation

**Problem:** Used in `slo_controller.py` (line 346), `cost_intelligence.py` (line 105), `merge_cycle.py` (line 88). Deprecated since Python 3.12; produces naive datetimes that can cause timezone bugs.

**Fix:** Replace with `datetime.datetime.now(datetime.timezone.utc)` everywhere. Grep + sed.

### 2.5 Hardcoded `PROJECT_PRIORITY_ORDER` in `db.py`

**Problem:** Line 86–101 hardcodes project priorities. Adding a new project requires a code change, deploy, and fleet restart.

**Fix:** Move to the `fleet_config` table (key: `PROJECT_PRIORITY_ORDER`, value: JSON array). Fall back to current hardcoded list if the config key is missing.

### 2.6 Resource Governor File Handle Leaks

**Problem:** `set_throttle()` and `current_limit()` use bare `open()` without `with` context managers (lines 391, 396). File handle leak if an exception occurs.

**Fix:** Wrap in `with open(...) as f:`.

---

## Tier 3 — Strategic, Queue as Backlog

### 3.1 Test Coverage Push (18% → 60%)

**Current state:** 52 of 284 source files have tests. Critical untested files include:
- `slo_controller.py` — the automated remediation brain
- `intake_watcher.py` — the intake pipeline
- `db.py` — the data layer
- `runner.py` (only partial coverage via integration tests)
- `agentic_coders.py` — the actual code generation dispatch
- `model_router.py` — model selection logic
- `retry_policy.py` — error classification

**Approach:** Generate a `PROMPT-test-coverage-push.md` intake file that decomposes into one task per critical untested module, ordered by blast radius:
1. `db.py` (everything depends on it)
2. `slo_controller.py` (safety system)
3. `intake_watcher.py` (work entry point)
4. `model_router.py` (cost/quality decisions)
5. `retry_policy.py` (error handling)
6. `agentic_coders.py` (execution engine)

### 3.2 CI/CD Pipeline (Currently None)

**Problem:** `lefthook.yml` is entirely commented out. No `.github/workflows/`. No linting config. Code quality is enforced only by the orchestrator's own merge train, which means quality gates only run *after* a task produces code, not during development.

**Fix — phased:**
1. **Phase 1:** Uncomment and configure `lefthook.yml` for pre-commit: `ruff check`, `ruff format --check`, `python -m pytest runner/tests/ -x -q`
2. **Phase 2:** Add a GitHub Actions workflow that runs on PR/push to master: full test suite + ruff + type checking
3. **Phase 3:** Add `pytest-cov` with a coverage floor (start at 18%, ratchet up as tests land)

### 3.3 Metrics & Dashboard

**Problem:** No Prometheus-style counters, no time-series data on claim latency, hook duration, retry rates, merge success rates over time. `orchestrator_metrics.py` produces point-in-time snapshots but no trends.

**Fix:** Add a lightweight `metrics.py` using the existing `resource_events` table:
- `metrics.count("task_claimed", project=p)`
- `metrics.timer("pre_hooks_total_ms", duration)`
- `metrics.gauge("queue_depth", n)`

Surface via the existing `generate_dashboard.py` HTML dashboard with time-series charts.

### 3.4 Import-Time Startup Optimization

**Problem:** `runner.py` imports 102 modules at startup (lines 20–102), many heavyweight. Startup is slow and fragile — any import-time side effect (DB query, file I/O) can prevent the runner from starting.

**Fix:** Lazy-import hooks that are only used in specific code paths:
```python
# Before: import cade_tournaments (always loaded)
# After:  loaded on first use
def _get_cade():
    import cade_tournaments
    return cade_tournaments
```

### 3.5 Planner JSON Parsing Robustness

**Problem:** `planner.py` line 68 uses `re.search(r"\[.*\]", r["text"], re.S)` which is greedy across newlines. If the model response contains brackets in prose before the JSON array, this captures invalid JSON.

**Fix:** Use a more targeted extraction: find the first `[` that starts a JSON array, then parse forward. Or require the model to wrap output in a fenced code block and extract from that.

### 3.6 `'_plan' in dir()` Anti-Pattern

**Problem:** Used ~18 times in `runner.py` to check if a local variable was assigned. `dir()` in a function is unreliable — it can include names from failed assignments.

**Fix:** Initialize with `_plan = None` before the try block, then check `if _plan is not None`.

---

## Tier 4 — Architectural (Requires Design Review)

### 4.1 Post-Hook Telemetry → Background Thread

The 15+ post-integration hooks (lines 1386–1544) run serially and block the task thread after merge. Move to a fire-and-forget background queue: `telemetry_queue.put((task, outcome))` → background worker processes them. The task thread is freed immediately.

### 4.2 Claim Cycle Visibility Dashboard

The main claim loop (lines 2300–2361) has no visibility into *why* slots aren't being filled. Add a structured reason for each claim cycle: "blocked by mem-gate" vs "blocked by capacity-pacer" vs "no QUEUED tasks" vs "all lanes full." Surface this in the fleet status dashboard so operators can diagnose utilization gaps instantly.

### 4.3 Hot Module Reload for Hooks

Currently, adding or modifying a hook requires restarting the runner. A plugin-style hook registry that discovers hooks via a directory scan (e.g., `runner/hooks/pre/*.py`) would allow hot-reloading hooks without fleet restarts.

### 4.4 Intake Watcher Dedup Optimization

`intake_watcher.py` does `db.select("tasks", {"select": "slug"})` — fetching ALL task slugs — twice per intake cycle (lines 162, 242). Cache the slug set with a 60s TTL, or better, push the uniqueness check to the DB via a unique constraint on `(project_id, slug)`.

---

## Summary Matrix

| # | Improvement | Impact | Effort | Risk |
|---|-------------|--------|--------|------|
| 1.1 | Structured logging | HIGH | LOW | NONE |
| 1.2 | Surface swallowed errors | HIGH | LOW | NONE |
| 1.3 | Parallelize pre-hooks | HIGH | MED | LOW |
| 1.4 | Fix claim_task N+1 | HIGH | MED | LOW |
| 1.5 | SLO fail-safe inversion | MED | LOW | NONE |
| 2.1 | Thread-safety audit | MED | MED | LOW |
| 2.2 | Task slicer atomicity | MED | LOW | NONE |
| 2.3 | Intake retry cap | MED | LOW | NONE |
| 2.4 | datetime.utcnow() fix | LOW | LOW | NONE |
| 2.5 | Dynamic project priority | MED | LOW | NONE |
| 2.6 | File handle leaks | LOW | LOW | NONE |
| 3.1 | Test coverage push | HIGH | HIGH | NONE |
| 3.2 | CI/CD pipeline | HIGH | MED | LOW |
| 3.3 | Metrics dashboard | MED | MED | NONE |
| 3.4 | Lazy imports | LOW | MED | LOW |
| 3.5 | Planner JSON robustness | LOW | LOW | NONE |
| 3.6 | dir() anti-pattern | LOW | LOW | NONE |
| 4.1 | Background telemetry | MED | MED | LOW |
| 4.2 | Claim visibility | MED | MED | NONE |
| 4.3 | Hot module reload | LOW | HIGH | MED |
| 4.4 | Intake dedup cache | LOW | LOW | NONE |

---

## Intake-Ready Task File

To queue Tier 1 items for the fleet, drop a `PROMPT-orchestrator-hardening.md` at repo root with the items above decomposed into canonical format. Tier 2+ should follow after Tier 1 merges validate the approach.
