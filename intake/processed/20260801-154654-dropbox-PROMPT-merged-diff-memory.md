# PROMPT: Merged-Diff Memory System (Task Spec)

**Date:** 2026-08-01  
**Task Slug:** `merged-diff-memory`  
**Scope:** Feature; integrates with auto-memory and fleet coordination  
**Status:** SPEC READY FOR INTAKE

---

## Intent

Implement a lightweight memory system that extracts and retains patterns from successfully merged branches/diffs. When a branch is merged to master, capture its diff summary (files changed, conflict resolution, commit pattern) into the auto-memory system at `~/.claude/projects/-Users-kpasch-Documents-beethoven-claude-orchestrator/memory/`. This allows future sessions and fleet agents to learn which patterns worked, reducing redundant exploration and speeding up adaptive reuse.

**Core mission:** Turn successful merges into retrievable exemplars for future work.

---

## Scope

**Add exactly one file:** `runner/merged_diff_memory.py` (module-level functions, fail-soft errors, module-level singleton pattern per project conventions).

**Integrate with:**
- Post-merge hook: Capture diffs when `git merge` completes (or detect via sentinel.py if branch is merged in main checkout)
- Auto-memory system: Write to `~/.claude/projects/{project-id}/memory/` with frontmatter
- Fleet config: Store summary count via `fleet_config` table (key: `ORCH_MERGED_DIFF_COUNT`)

**Do NOT modify:**
- Worktree sentinel.py
- Intake watcher
- Git hooks directly (detect merges, don't intercept them)

---

## Implementation

### `runner/merged_diff_memory.py`

Provide **module-level functions** (not a class API) that delegate to a thread-safe singleton instance.

#### Constants

```python
MEMORY_DIR = Path.home() / ".claude" / "projects" / "{project_id}" / "memory"
SUMMARY_FIELDS = ["files_changed", "insertions", "deletions", "conflict_resolutions", "branch_name", "merge_date"]
DEFAULT_PROJECT_ID = "claude-orchestrator"
```

#### Module-level function: `capture_merge(branch_name: str, base_commit: str, merge_commit: str) -> bool`

**Behavior:**
1. Compute diff: `git diff {base_commit}..{merge_commit}` (or `git show {merge_commit}` if only merge_commit provided).
2. Parse diff to extract:
   - `files_changed`: list of modified file paths (dedupe, up to 50 files; if >50, note as `+N more`)
   - `insertions`, `deletions`: line counts
   - `conflict_resolutions`: count of `<<<<<<< / =======` conflict markers in commits (0 if none)
   - `branch_name`: input branch_name
   - `merge_date`: ISO-8601 UTC timestamp
3. **Write to auto-memory:**
   - File: `merged_diff_{sanitized_branch_name}.md`
   - Frontmatter: `name`, `description`, `metadata.type: 'reference'`
   - Body: YAML with fields above + summary paragraph
   - Example filename: `merged_diff_prompt_evolver_ucb1.md`
4. **Update fleet config:**
   - Call `db.upsert("fleet_config", {"key": "ORCH_MERGED_DIFF_COUNT", "value": str(count+1)})`
   - Do NOT raise if this fails; log a warning and continue.
5. **Return:** `True` if memory file written successfully, `False` on any error (bad git refs, no diffs, write failure). Never raise.

**Error handling:** On git error (bad ref, not a repo), file I/O error, or database error, log with `logging.warning(...)` and return `False`. This follows fail-soft pattern.

**Return type:** `bool`

---

#### Module-level function: `retrieve_exemplars(keyword: str = None, limit: int = 5) -> list[dict]`

**Behavior:**
1. Scan `~/.claude/projects/{project_id}/memory/merged_diff_*.md` files.
2. For each file, parse frontmatter and body YAML.
3. If `keyword` provided: filter files where filename or summary contains keyword (case-insensitive).
4. Return up to `limit` most recent by `merge_date`.
5. Return format: `[{name, branch_name, files_changed, merge_date, summary}, ...]`
6. **Error handling:** If directory doesn't exist or is unreadable, return `[]` silently (fail-soft).

**Return type:** `list[dict]`

---

#### Module-level function: `is_merge_candidate(commit_message: str) -> bool`

**Behavior:**
1. Heuristic: Return `True` if commit_message contains "Merge branch" or "Merge pull request" (standard git merge message).
2. Return `False` otherwise.
3. No errors; always succeeds.

**Return type:** `bool`

---

### Integration Point: Detection

**Suggested caller (not implemented by this module):**
- In a post-merge context (e.g., sentinel.py detecting `git branch --no-merged` → `git branch --merged`), call `capture_merge(branch_name, base, merge_commit)` to record the merge.
- Or: In operator/task completion handlers, call `capture_merge(...)` after a successful merge to master.

The module itself is agnostic to how/when it's invoked; it simply captures and stores.

---

## Acceptance Criteria

- [ ] `runner/merged_diff_memory.py` exists with three module-level functions (capture_merge, retrieve_exemplars, is_merge_candidate).
- [ ] `capture_merge(branch, base, merge_commit)` computes git diff and extracts files_changed, insertions, deletions, conflict_resolutions.
- [ ] `capture_merge()` writes to `~/.claude/projects/{project_id}/memory/merged_diff_*.md` with valid frontmatter and YAML body.
- [ ] `capture_merge()` updates fleet_config with ORCH_MERGED_DIFF_COUNT; does not raise if database fails.
- [ ] `capture_merge()` returns `True` on success, `False` on any error (git, I/O, DB). Never raises.
- [ ] `retrieve_exemplars(keyword, limit)` scans memory dir, filters by keyword, returns up to limit dicts.
- [ ] `retrieve_exemplars()` returns `[]` if memory dir missing or unreadable (fail-soft).
- [ ] `is_merge_candidate()` returns True for "Merge branch" / "Merge pull request", False otherwise.
- [ ] All functions follow module-level singleton pattern; use threading.Lock() to protect shared state.
- [ ] Tests cover: successful capture, git errors, file I/O errors, db errors (all logged, no raise), retrieve with/without keyword, empty memory dir.
- [ ] No modifications to worktree sentinel, intake watcher, or git hooks.
- [ ] Build/tests pass cleanly.

---

## Technical Notes

**On project_id:**
The default is `claude-orchestrator`. May be parameterized via environment variable `ORCH_PROJECT_ID` if this system scales to multiple projects.

**On memory file format:**
- Frontmatter: `name: merged_diff_<sanitized_branch>`, `description: <one-liner>`, `metadata.type: reference`
- Body: YAML block with fields from SUMMARY_FIELDS, then a short markdown summary paragraph
- Example:
  ```markdown
  ---
  name: merged_diff_prompt_evolver_ucb1
  description: UCB1 bandit system for prompt template selection
  metadata:
    type: reference
  ---
  
  ## Merge Summary
  
  - branch: agent/prompt-evolver-ucb1
  - date: 2026-08-01T14:23:45Z
  - files_changed: [runner/prompt_evolver.py, runner/tests/test_prompt_evolver.py]
  - insertions: 450
  - deletions: 20
  - conflict_resolutions: 0
  
  This merge introduced UCB1 multi-armed bandit for prompt template selection per message kind...
  ```

**On retrieve_exemplars:**
Keyword search is simple substring match (not regex). Searches in filename and summary section only, not full body (to avoid expensive parsing).

**On thread safety:**
If multiple agents/processes call capture_merge concurrently, use a module-level Lock to serialize memory writes. Fail gracefully if lock cannot be acquired (log warning, return False).

---

## Files Changed

| File | Status | Notes |
|------|--------|-------|
| `runner/merged_diff_memory.py` | **Create** | Module with capture_merge(), retrieve_exemplars(), is_merge_candidate() |
| `~/.claude/projects/claude-orchestrator/memory/merged_diff_*.md` | **Create** (multiple) | Auto-generated exemplar files from successful merges |
| `fleet_config` table | **Update** (via db) | ORCH_MERGED_DIFF_COUNT key incremented on each capture |
| (all others) | Unchanged | No modifications to runner.py, sentinel.py, intake, git hooks, etc. |

---

## Success Metrics

1. **Functional:** Module imports without error; all three functions available and callable.
2. **Integration:** Post-merge, exemplar file appears in `~/.claude/projects/claude-orchestrator/memory/`.
3. **Reuse:** Future sessions can call `retrieve_exemplars(keyword="template")` and get past prompt_evolver merge summary.
4. **Resilience:** Network/DB failures do NOT wedge the system; fail-soft logging in place.
5. **Tests:** Minimum 8 test cases covering success path, git errors, I/O errors, DB errors, retrieval with/without keyword.

---

## Placement in Intake Queue

This spec is ready for `intake_watcher.py` to decompose and queue for parallel execution. Entry point: `PROMPT-merged-diff-memory.md` in repo root or `intake/` directory.

**Recommended next step:** Drop this file into the intake folder and let the fleet queue the work, or submit directly to a free runner slot.
