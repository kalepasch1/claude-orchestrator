# patch-template Branch Logic Analysis

**Task:** canary-gpt-1-slice-2-analyze-patch-template-branch-logic  
**Date:** 2026-07-09  
**Scope:** How the patch-template system identifies, uses, and reacts to missing/stale branches; rebase conflict failure paths; existing recovery mechanisms.

---

## Current State

### patch_templates.py — no branch awareness

`patch_templates.py` operates purely at the prompt/text level. It:
- Builds a prompt scaffold from task intent words + nearest merged diffs (via `merged_diff_library.find()`)
- Stores templates in `knowledge` table or `.runtime/patch_templates.jsonl` as fallback
- Has **zero branch awareness** — cannot detect missing/stale branches, does not read or write git refs

Branch name is never consulted. Source/target branch context is never injected into the scaffold.
This means an agent working from a patch-template gets no hint about which base branch to target.

### Branch identification pattern

Branch names follow `agent/<slug>` (set at `approval_merge.py:290`, `patch_recovery.py:21`).
Existence is tested with:
```python
# approval_merge.py:91
def _branch_exists(repo, branch):
    return subprocess.run(["git", "rev-parse", "--verify", branch], ...).returncode == 0
```
`base_branch` is read from the task row or the project's `default_base`.

---

## Missing-Branch Detection Path

When a task's branch is gone at merge time (`approval_merge.py:296-305`):

1. `_branch_exists(repo, branch)` → False
2. `agentic_repair.repair_patch(t, ..., category="missing-branch", directive="Reconstruct …")` is called
3. Approval card marked `decided_by="{MARK}:branch-missing"`
4. Task requeued as QUEUED (full agent re-run)

**Gap:** `approval_merge.py` skips straight to agent re-run and never calls `patch_recovery.recover()`.
The cheaper three-method mechanical recovery exists but is **not wired into this path**.

---

## patch_recovery.py — Three-Method Mechanical Recovery (unused in main flow)

`patch_recovery.recover(repo, slug, base, project)` tries:

### Method 1: Stored patch replay
- Calls `task_artifacts.get_patch(slug)` → retrieves `patch_diff` stored at task completion
- Creates a fresh branch from base in an isolated worktree
- Applies with `git apply --3way`, falls back to `--reject`
- Commits and verifies the branch is ahead of base

**Failure path:** If `task_artifacts` has no entry for `slug` (common for pre-artifact tasks, DB failures, or tasks that never reached DONE/MERGED) → returns `{"ok": False, "reason": "no stored patch"}`.

### Method 2: Reflog cherry-pick
- Scans `git reflog` for any entry containing the slug
- Verifies the found SHA is an ancestor of base then recreates the branch

**Failure path:** If reflog has been pruned or the task never committed to this repo → `"slug not in reflog"`.

### Method 3: Template adaptation — BUG

```python
# patch_recovery.py:162-166
def _template_adaptation(repo, slug, branch, base, project=None):
    ...
    best_match = ...  # finds a similar merged artifact
    if not best_match or best_score < 2:
        return {"ok": False, ...}

    # Try applying the similar diff
    return _replay_stored_patch(repo, slug, branch, base)  # BUG: uses slug, not best_match
```

After finding a similar merged diff (`best_match` contains `patch_diff` from a different task),
the code calls `_replay_stored_patch(repo, slug, branch, base)` — which looks up `task_artifacts.get_patch(slug)`,
i.e., the **original missing task's patch**, not the found similar diff.

Since the original patch is missing (that's why we reached method 3), this always returns
`"no stored patch"`. Method 3 effectively always fails. The `best_match` object is found but never applied.

---

## Stale-Branch / Rebase Conflict Path

`_integrate(repo, branch, base)` in `approval_merge.py`:

1. Calls `_free_branch(repo, branch)` — removes any leftover worktree holding the branch (fixes phantom CONFLICT bug from 2026-07-08)
2. Checks if branch is strictly ahead of base; if diverged, calls `_rebase_isolated(repo, base, branch)`
3. `_rebase_isolated` runs in an **isolated worktree** (`-wt/rebase-<branch>`) to avoid mutating the main checkout

**Self-heal on CONFLICT** (`approval_merge.py:323-338`):
- Deletes stale branch
- Calls `agentic_repair.repair_patch(..., category="conflict", directive="Rebuild on fresh {base}")`
- Capped at `MERGE_CONFLICT_REDO_CAP` (default 2) via `transient_retries`
- Reopens approval card as pending

**Failure path for rebase conflicts:**  
If both base and branch have diverged significantly, `git rebase` produces conflicts. `--abort` restores the branch ref to pre-rebase state (correct). The task is re-queued for full agent rebuild. No partial conflict resolution is attempted.

---

## Runner Exception Root Cause

```
[Errno 2] No such file or directory: '/Users/kpasch/Documents/beethoven/claude-orchestrator'
```

The path exists on disk (confirmed). The exception originates from a subprocess spawned by the runner
without an accessible working directory. Most likely triggers:
- launchd agent with restricted macOS TCC/sandbox access running `git` in that path
- Race with worktree operations: `_free_branch` or `git worktree prune` momentarily moves `.git/worktrees` metadata
- `os.makedirs(os.path.dirname(wt), exist_ok=True)` in `_replay_stored_patch` (patch_recovery.py:57) using `os.path.dirname(repo)` which resolves to a path that's inaccessible in the subprocess context

The runner has **no retry/fallback** around repo-path validation before entering git operations.

---

## Merged-Diff Library / Cache Hints

| Module | Role | Branch-aware? |
|---|---|---|
| `merged_diff_library.py` | Indexes merged diffs by keyword/symbol overlap | No |
| `patch_transplant.py` | Pre-claim hook: prepends PATCH TRANSPLANT hint | No |
| `patch_templates.py` | Pre-claim hook: prepends scaffold | No |
| `patch_recovery.py` | Mechanical branch recovery | Yes — but unused in missing-branch flow |
| `task_artifacts.py` | Stores patch_diff, commit_sha, touched_files at completion | Indirectly |

---

## Identified Gaps

| # | Gap | File | Lines | Impact |
|---|---|---|---|---|
| 1 | `_template_adaptation` applies wrong slug to `_replay_stored_patch` | `patch_recovery.py` | 162-166 | Method 3 always fails; template recovery is dead code |
| 2 | `approval_merge.py` missing-branch path skips `patch_recovery.recover()` | `approval_merge.py` | 296-305 | Every missing-branch triggers expensive agent re-run; mechanical recovery is never tried |
| 3 | `patch_templates.py` injects no source/target branch context | `patch_templates.py` | 45-60 | Agent may target wrong base branch when working from scaffold |
| 4 | No retry on `[Errno 2]` repo-path failures in runner | `patch_recovery.py` | 56-58 | Transient filesystem unavailability causes runner exception rather than soft retry |
| 5 | No test coverage for `patch_recovery.py` | `runner/tests/` | — | Bugs like gap #1 go undetected |

---

## Potential Improvements

1. **Fix `_template_adaptation` bug** (gap #1): pass the found similar diff directly to a new helper that applies an arbitrary diff, not the original task's stored patch.

2. **Wire `patch_recovery.recover()` into `approval_merge.py`** (gap #2): before calling `agentic_repair`, try mechanical recovery. Only re-queue agent if all three methods fail.

3. **Inject base branch into patch-template scaffold** (gap #3): add `"Base branch: {task.get('base_branch') or 'main'}"` to the `Implementation slots` section.

4. **Guard repo-path access** (gap #4): validate `os.path.isdir(repo)` before any git subprocess; return a soft error dict rather than raising `[Errno 2]`.

5. **Add tests for `patch_recovery.py`** (gap #5): at minimum cover method 3 bug regression.
