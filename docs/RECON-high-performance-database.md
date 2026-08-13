# Recon Map — "upgrade to a high-performance database" (slice 3)

Reconnaissance only. **No production code changed in this slice** — per the task's own
acceptance criteria ("Do not add production code yet"). This document is the deliverable:
it names the owner module, the current DB access layer, the smallest target symbol set,
the base branch, and the real build/test command with its captured output.

## 1. Base branch

| Item | Value |
| --- | --- |
| Repo | `/Users/kpasch/Documents/beethoven/claude-orchestrator` |
| `origin/HEAD` | `refs/remotes/origin/master` |
| `projects.default_base` (beethoven) | `master` |
| `tasks.base_branch` for this slice | `master` |

**No mismatch to repair.** All three agree on `master`. The repo does not use `main`.
`runner/db.py::_guard_task_base_branch` (line 944) already corrects a hardcoded
`tasks.base_branch` back to `projects.default_base` at claim time, so drift is
self-healing; there is nothing for this slice to fix.

## 2. Owner module and current database access layer

| Role | Path | Notes |
| --- | --- | --- |
| DB access layer (owner) | `runner/db.py` | 2,221 lines. Single chokepoint for all persistence. |
| Transport core | `runner/db.py::_req` (460), `runner/db.py::_req_one` (503) | Every read and write funnels through these two. |
| Health / failover | `runner/db_health.py`, `runner/db.py::_endpoints` (438), `_base_urls` (451), `_pin` (431) | Multi-endpoint failover with a pinned active base. |
| Preview/branch DB | `runner/preview_db.py` | Ephemeral preview instances. |
| Migrations | `runner/apply_sql_migrations.py`, `runner/new_migration.py` | SQL applied via Supabase. |
| Caches in front of DB | `runner/result_cache.py`, `runner/session_cache.py`, `runner/prompt_result_cache.py`, `runner/build_cache.py`, `runner/warm_pool.py` | Existing mitigation layers; reuse before adding new ones. |

Import convention is flat, not packaged: **383 modules use bare `import db`** (plus 16
variants), relying on `runner/` being on `sys.path`. `runner/` has no `__init__.py`.
Any change to `db.py`'s public surface therefore fans out across the whole runner.

### Call-site volume (the reason this is a performance problem)

| Symbol | Call sites in `runner/*.py` |
| --- | --- |
| `db.select` | 1,232 |
| `db.rpc` | 31 |
| `db.select_all` | 6 |

## 3. Smallest target symbol set for the upgrade

The public surface that must keep its exact signature (any change here is a 1,200+
call-site migration, so the upgrade must be *behind* these, not *through* them):

```
runner/db.py::select(table, params=None)              # line 608
runner/db.py::select_all(table, params=None, ...)     # line 637
runner/db.py::count(table, params=None)               # line 684
runner/db.py::insert(table, row, upsert=False)        # line 1041
runner/db.py::upsert(table, row)                      # line 1202
runner/db.py::update(table, match, patch)             # line 1207
runner/db.py::rpc(fn, args)                           # line 1248
```

The symbols that should actually change — all private, all inside `db.py`:

```
runner/db.py::_req(method, path, body, headers, params)      # line 460
runner/db.py::_req_one(base, method, path, qs, data, h, ...) # line 503
```

**Primary bottleneck:** `_req_one` calls `urllib.request.urlopen(req, timeout=_to)`
(line 518; a second at line 701 in the `select_all` paging path). `urlopen` opens a
**new TCP + TLS connection per request** and closes it — there is no keep-alive, no
connection pool, and no session reuse anywhere in `db.py` (grep for
`HTTPSConnection|requests.Session|opener` returns only these two `urlopen` sites).
At 1,232 `db.select` call sites, every hot loop pays a full TLS handshake per row-set.

Secondary targets, in dependency order:

1. `PAGE_SIZE = 1000` (line 630) / `SELECT_ALL_MAX_ROWS` (line 634) — `select_all`
   pages serially at 1,000 rows with a fresh connection per page.
2. `HTTP_RETRIES` (250), `HTTP_RETRY_STATUSES` (256), `CORE_RETRY_RPCS` (258) — the
   retry budget is per-endpoint and interacts with the failover loop in `_req`; a
   pooled transport changes the cost model these constants were tuned against.
3. `_warn_if_truncated` (569) — already flags silent truncation; keep as the
   correctness guard for any new paging strategy.

**Constraint to preserve:** `_req` deliberately raises `TransientDBError` (line 46)
rather than a bare `URLError` when every endpoint is unreachable, and deliberately
re-raises `HTTPError` without failing over. The header comments at lines 471–500
record why (1,995 + 1,803 crash-loop tracebacks). A pooled transport must keep both
behaviours; `crash_loop_detector` classifies `TransientDBError` as environmental.

## 4. Build/test command and captured output

The real project command is `npm test`, which is defined in `package.json` as:

```
python3 -m pytest runner/tests/ -x --tb=short -q 2>&1 || true
```

Run on this branch (base `master` @ `64a7b0ef`):

```
.......................F
=================================== FAILURES ===================================
_______ TestMarkExhaustedBackoff.test_second_exhaustion_doubles_cooldown _______
runner/tests/test_account_pool_cooldown.py:100: in test_second_exhaustion_doubles_cooldown
    assert pool.state[acct["name"]]["exh_hits"] == 2
E   assert 3 == 2
----------------------------- Captured stdout call -----------------------------
[notify] Account 'test-account' hit its limit -> rotated to '{'name': 'default', 'type': 'login'}'.
[notify] Account 'test-account' hit its limit -> rotated to '{'name': 'default', 'type': 'login'}'.
=========================== short test summary info ============================
FAILED runner/tests/test_account_pool_cooldown.py::TestMarkExhaustedBackoff::test_second_exhaustion_doubles_cooldown
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed, 23 passed, 1 skipped, 2 warnings in 3.96s
```

**Exact current failure:** `runner/tests/test_account_pool_cooldown.py::TestMarkExhaustedBackoff::test_second_exhaustion_doubles_cooldown`
— `assert 3 == 2` on `pool.state[acct["name"]]["exh_hits"]`. `mark_exhausted` in
`runner/account_pool.py` increments `exh_hits` one time more than the test expects
(three increments for two exhaustion events). Unrelated to the DB layer; it is `-x`,
so it masks the rest of the suite and must be cleared before any DB change can be
validated by `npm test`. Filed as the blocking precondition for slice 4.

Note the suite is invoked as `runner/tests/`, **not** `tests/`. The top-level
`tests/` directory cannot be collected at all — `python3 -m pytest tests/` aborts with
12 `ModuleNotFoundError: No module named 'runner.<mod>'; 'runner' is not a package`
errors, because `runner/` lacks `__init__.py` and `import runner` resolves to the
module `runner/runner.py`. Use `npm test` as the canonical command.

## 5. Prior merged patterns to adapt

Existing in-repo precedent for staged, behind-the-facade infrastructure swaps:

- `runner/db.py::_pin` / `_base_urls` / `_endpoints` — the multi-endpoint failover was
  added under the existing `select`/`insert` API with no call-site changes. Same shape
  the connection-pool change should take.
- `runner/warm_pool.py`, `runner/model_pool_cache.py` — established pooling conventions
  in this codebase (module-level singleton + `acquire()`); reuse rather than inventing
  a new pool idiom. `CONVENTION_LINT.md` Rule 3 enforces the `acquire()` shape.
- `runner/result_cache.py` — precedent for a read cache in front of `db.select`.

## 6. Handoff to slice 4

1. Fix `test_second_exhaustion_doubles_cooldown` so `npm test` reaches a clean baseline.
2. Replace the two `urllib.request.urlopen` sites in `runner/db.py` with a pooled,
   keep-alive transport held as a module-level singleton with `acquire()`, preserving
   `TransientDBError` classification and the no-failover-on-HTTPError rule.
3. Re-run `npm test`; no `db.*` call site should change.
