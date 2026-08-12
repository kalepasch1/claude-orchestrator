# relfix-local-lora-distill — owner location & baseline report

**Task:** `relfix-local-lora-distill-add-test-check-locate-owner-and-baseline`
**Repo:** `claude-orchestrator` @ `origin/master` (`c635b983`)
**Date:** 2026-08-12
**Acceptance:** (1) report naming exact files/functions/helper APIs, (2) build succeeds,
(3) existing tests pass — **with no code changes**. This document is the deliverable;
no source file was modified on this branch.

---

## 1. Template-ID search: `33a1f2b7d5ee` does not exist in the repo

Full-tree scan (excluding `.git`, `node_modules`, `__pycache__`, `.pytest_cache`,
`.runtime`) for the template ID and every intent token in the prompt:

| Token | Tracked-source hits | Where found |
|---|---|---|
| `33a1f2b7d5ee` | 0 | — |
| `67c46e939ecf` | 0 | — |
| `bf0ed633a9c6` | 0 | only `.recovery-intent-*.txt` (untracked scratch) |
| `c1486760bb7d` | 0 | only `.recovery-intent-*.txt` (untracked scratch) |
| `9d0155` | 0 | only `.recovery-intent-*.txt` (untracked scratch) |
| `aaac4e` | 0 | only `.recovery-intent-*.txt` (untracked scratch) |

**Conclusion:** the hex tokens are queue-side intent digests emitted by the recovery
pipeline into untracked `.recovery-intent-*.txt` files at repo root. They are not
identifiers of anything in the source tree. `PATCH TEMPLATE 33a1f2b7d5ee` has no owner
module because the template was never persisted — template bodies are stored per-task
(see §2), not committed.

---

## 2. Owner modules by concern

### 2.1 Template patching / rendering — `runner/patch_templates.py`

The module that builds, stores, looks up and injects patch templates.

| Symbol | Line | Role |
|---|---|---|
| `MARK = "[patch-template:"` | 23 | Note marker used to bind a template ID to a task row |
| `WORD`, `SYMBOL_HINT` | 24–25 | Token extraction regexes driving template identity |
| `_words(text)` | 28 | Tokenizer (`[a-z0-9_]{4,}`) — the source of the hex-ish intent tokens |
| `_intent(task)` | 32 | Reduces a task to its intent token set |
| `_id(task)` | 37 | **Derives the 12-hex template ID** (e.g. `33a1f2b7d5ee`) from intent |
| `build(task)` | 42 | Renders the template body for a task |
| `_fallback_path()` | 78 | Directory/file handling: on-disk fallback store location |
| `lookup(template_id)` | 84 | **Resolves an ID → body**; returns empty when unknown (fail-soft) |
| `_store(task, template_id, body)` | 120 | Persists body against the task row |
| `inject_prompt(task)` | 140 | Splices the rendered template into the agent prompt |
| `_get_project(project_id)` | 149 | Project lookup helper |
| `_ensure_branch(task)` | 161 | Branch materialization for the template's target |
| `pre_claim_hook(task)` | 204 | Pipeline entry point — runs before a task is claimed |

`_id()` is why the ID in the prompt resolves to nothing: it is a **content hash of the
task's intent tokens**, computed at claim time. It is stable only while the task text is
stable; nothing writes the ID into tracked source.

### 2.2 Prior-patch reuse (the "transplant" path) — `runner/reuse_first.py`

| Symbol | Line | Role |
|---|---|---|
| `VECTOR_THRESHOLD = 0.85`, `KEYWORD_THRESHOLD = 0.35` | 28–29 | Similarity gates |
| `NOTE_MARK = "[reuse-first: matched"` | 30 | Binding marker on the task row |
| `_jaccard(a, b)` | 39 | Similarity metric (the `similarity=0.515` figures in prompts) |
| `find_reusable(task)` | 77 | Locates a prior merged patch to transplant |
| `rewrite_prompt(task, hit)` | 133 | Rewrites the prompt to prefer the prior patch |
| `pre_claim_hook(task)` | 149 | Pipeline entry point |

### 2.3 Merged-diff memory (the corpus reuse draws from) — `runner/merged_diff_memory.py`

Two cooperating layers in one module:

*Capture layer* — `_get_merged_commits()` (61), `_extract_patterns_from_commit()` (81),
`_extract_rules()` (146), `_save_to_memory()` (158), `_update_memory_index()` (222),
`_prune_old_entries(days=90)` (257), `capture_to_memory()` (285), `run()` (340).
Directory/file handling: `_ensure_dirs()` (39), roots from `CLAUDE_ORCH_HOME` /
`CLAUDE_MEMORY_ROOT` (30–32), lookback `MERGED_MEMORY_LOOKBACK` (33), error sink
`ERROR_LOG` (34) via `_log_error()` (47).

*Store layer* — `MEMORY_DIR` / `MERGED_DIFF_FILE` / `MAX_STORED_MERGES = 50` (410–412),
`_safe_run()` (415), `_read_memory()` (424), `_write_memory()` (436),
`capture_merge()` (465), `get_recent_merges()` (503), `stats()` (509),
`invalidate()` (520), `recent()` (525).

`stats()` / `invalidate()` are the repo's standard module-level-singleton observability
pair (see CLAUDE.md); reuse them rather than reaching into module globals.

### 2.4 Excerpt / drafting logic — `runner/prompt_assembler.py`

| Symbol | Line | Role |
|---|---|---|
| `MAX_AGENT_PROMPT_CHARS` (`ORCH_MAX_AGENT_PROMPT_CHARS`, 36000) | 41 | Prompt cap |
| `BRIEF_MAX_BYTES` (`ORCH_BRIEF_MAX_BYTES`, 4096) | 42 | **Excerpt cap** for project briefs |
| `REUSE_FIRST` | 44 | The cost-discipline preamble spliced into every prompt |
| `ASSEMBLY_LOG` | 53 | `$CLAUDE_ORCH_HOME/prompt_assembly.jsonl` |
| `_cap(prompt)` | 56 | Truncation helper |
| `_project_brief(project, repo)` | 72 | Reads + excerpts the project brief |
| `_distilled_body(task_body, task, project)` | 114 | **Drafting/distillation entry point** |
| `_log_assembly(...)` | 125 | Layer accounting |
| `assemble(task_body, *, project, repo, kind, source, slug, ...)` | 135 | Public API |
| `stats(limit=200)` / `invalidate()` | 243 / 259 | Singleton observability pair |

Both env knobs are `ORCH_`-prefixed, so they are fleet-pushable via `fleet_control.py`
per CLAUDE.md.

### 2.5 Retry scope — `runner/runner.py` + `runner/retry_budget.py`

| Location | Role |
|---|---|
| `runner/runner.py:1045` | `_max_attempts = 4` default |
| `runner/runner.py:1048` | `retry_budget.max_attempts(t)` — per-task override |
| `runner/runner.py:1050` | Records `retry-budget: max_attempts=N` on the task note |
| `runner/runner.py:1053` | `while attempt < _max_attempts:` — the retry loop |
| `runner/runner.py:3293` | `_block_or_retry(t, note)` — terminal disposition |

Retry scope is **per task attempt**, not per file or per patch; a template that fails to
apply consumes one attempt of the task's budget.

### 2.6 Static gate that guards all of the above — `runner/static_sanity.py`

`check(paths)` (69), `assert_critical(caller)` (82), `audit()` (54), `all_modules()` (36),
`CRITICAL_MODULES` (28). Called at `runner/merge_train.py:2190` and
`runner/blocked_triage.py:405`. Fail-soft when pyflakes is absent.

---

## 3. Baseline (measured, not assumed)

Interpreter: `/opt/homebrew/bin/python3.14` with `PYTHONPATH=.`.
(`/usr/bin/python3` is Xcode's 3.9 and is **not** the interpreter the fleet uses — the
`__pycache__` artifacts throughout the tree are `cpython-314`.)

### 3.1 Build — PASS

```
python3 -m compileall -q runner tools lib   → exit 0
cd runner && python3 static_sanity.py       → clean, exit 0
```

### 3.2 Test suite — **NOT green**

```
PYTHONPATH=. python3.14 -m pytest tests/ -q --continue-on-collection-errors
→ 22 failed, 933 passed, 8 warnings, 11 errors in 42.68s
```

Acceptance criterion (3) — "all existing tests pass with no code changes" — **is not met
at baseline**, and cannot be met by this task, which is scoped to add no code. Recorded
here so the next attempt does not misattribute these failures to its own diff.

**11 collection errors — order-dependent, not real import breakage.**
`test_assumptions_ledger`, `test_commit_containment`, `test_decompose_idempotency`,
`test_differential_gate`, `test_enqueue`, `test_evidence_gate_check`,
`test_prompt_evolver_exploration`, `test_reaudit_merged`, `test_scope_gate`,
`test_self_audit_rerun`, `test_vacuity_gate` — all fail with
`No module named 'runner.X'; 'runner' is not a package`. Each of these passes collection
when run alone. `runner/__init__.py` exists, so the package is well-formed; the cause is
that an earlier-collected test does `sys.path.insert(0, <repo>/runner)`, after which
`runner/runner.py` shadows the `runner` package for every later import. This is a test
isolation defect in the suite, not a defect in the modules under test.

**22 failures, by cluster:**

| Cluster | Tests | Note |
|---|---|---|
| `test_core_retry_rpcs.py` | 7 | Retry/backoff behaviour for core RPCs — same subsystem as §2.5 |
| `test_db_connectivity.py` | 6 | Network/auth/fail-soft paths |
| `test_merged_diff_memory_write.py` | 4 | Write-failure fail-soft paths in §2.3 |
| `test_validate_canary.py` | 2 | **Live defect** — see below |
| `test_env_safety.py` | 1 | `test_no_hardcoded_secrets_in_source` |
| `test_git_identity_and_verified_firing.py` | 1 | `test_no_runner_module_hardcodes_a_blocked_email` |
| `test_cowork_assemble_args.py` | 1 | `test_help_or_invalid_slug_does_not_crash` |

**Confirmed live defect found while baselining.** `runner/canary.py` defines
`validate_canary` **twice, verbatim** (lines 63–76 and 78–91) and both copies call an
undefined `_log`; the module never imports `logging` and never binds `_log`. Any call to
`validate_canary()` raises `NameError` at call time. `runner/static_sanity.py.audit()`
reports 6 undefined-name findings for it at `canary.py:69,72,74,85,88,90`, but
`canary.py` is **not** in `CRITICAL_MODULES`, so `assert_critical()` does not gate on it
and the module ships broken. This is the exact "overwrite dropped the definition, the
call site survived" class the module's own docstring says it exists to stop — the gate
simply is not looking at that file. Filed as a separate implementation task; not fixed
here, because this branch must produce no code changes.

---

## 4. Recommendations for the next attempt

1. Do not chase `33a1f2b7d5ee`. Template IDs are derived at claim time by
   `patch_templates._id()`; resolve via `patch_templates.lookup()` at runtime or accept
   that the template is gone.
2. Add `canary.py` (and `periodic.py`) to `static_sanity.CRITICAL_MODULES` and fix the
   `_log` binding — that alone clears 2 of the 22 failures and closes the gate gap.
3. Give the suite a root `conftest.py` that pins `sys.path` once, so the 11
   order-dependent collection errors stop masking real regressions.
4. Treat `933 passed / 22 failed / 11 errors` as the reference baseline for this commit.
   Any future run that reports fewer passes has regressed.
