# Test-Impact Incremental Build — Sub-task Breakdown

Parent task: `test-impact-incremental-build`

The original task involved git filter-repo (security-sensitive, quarantined).
This breakdown defines 3 safe, independently mergeable sub-tasks that deliver
incremental test-impact analysis **without any git history rewriting**.

---

## Sub-task 1: `test-impact-analyzer`

**File**: `runner/test_impact.py`
**Status**: stub created

A pure function that reads `git diff --name-only` output and maps changed files
to affected test files using import-graph analysis.

**Scope**:
- Accept a list of changed file paths (strings).
- Apply path heuristics: `runner/foo.py` → `tests/test_foo.py`,
  `server/bar.py` → `tests/test_bar.py`, etc.
- Parse Python imports to build a reverse-dependency graph so that changing
  a utility module surfaces all tests that transitively import it.
- Return deduplicated list of test file paths.

**Safety**: No git history rewriting. Reads `git diff` output only.

---

## Sub-task 2: `test-impact-cache`

**File**: `runner/test_cache.py`

Stores file-to-test mappings in a JSON cache and invalidates entries when
the source file changes (mtime / content hash).

**Scope**:
- Read/write `~/.cache/orchestrator/test_impact_cache.json`.
- Key = source file path, value = `{tests: [...], hash: "sha256:..."}`.
- On cache miss or hash mismatch, return `None` so the analyzer re-computes.
- Pure I/O — no git operations, no subprocess calls.

**Safety**: File I/O only. No git history rewriting.

---

## Sub-task 3: `test-impact-runner-integration`

**File**: changes to existing runner pipeline

Wire `test_impact` + `test_cache` into the runner as an optional
`--incremental` flag. When set, only affected tests are executed.

**Scope**:
- Add `--incremental` CLI flag to the test runner entry point.
- Before running pytest, call `changed_files_to_tests()` with the diff.
- Pass the resulting test list to pytest via `-k` or direct file args.
- Fall back to full test suite if the impact analysis returns an empty set
  (conservative: run everything rather than nothing).

**Safety**: Additive change behind a flag. Default behaviour unchanged.
