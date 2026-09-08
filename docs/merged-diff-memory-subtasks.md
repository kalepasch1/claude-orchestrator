# merged-diff-memory: Sub-task Decomposition

Split date: 2026-09-08
Parent task: `dropbox-prompt-merged-diff-memory-system-task-spec-group-7-split-the-build-task-`

## Context

The core cache layer of `merged_diff_memory.py` is complete and tested (50+ cases).
Four pieces remain to complete the pattern-extraction pipeline. Each sub-task below
is independently buildable and testable — no sub-task depends on another.

---

## Sub-task 1: quality_gate in learn_from_merges

**File:** `runner/learn_from_merges.py`
**Function:** `quality_gate(msg: str, diff: str) -> tuple[bool, str]`

Filter merge commits by quality threshold before extracting patterns.
Return `(True, "")` when the commit has substantive code changes worth learning
from; return `(False, reason)` for trivial, merge-only, or auto-generated commits.

**Acceptance test** (`runner/tests/test_quality_gate.py`, minimum 8 cases):
- `quality_gate("Merge branch 'agent/fix-typo'", "diff --git a/README.md...\n-old\n+new")` with <5 changed lines → `(False, "trivial")`
- `quality_gate("agent: implement rate limiter", <diff with 40+ changed lines>)` → `(True, "")`
- `quality_gate("", "")` → `(False, "empty commit")`
- `quality_gate("Merge pull request #42", <auto-merge diff>)` → `(False, "merge-only")`
- Commits touching only `.md` or `.txt` files → `(False, "docs-only")`
- Commits with `[skip-learning]` in message → `(False, "opt-out")`
- Commits with mixed code+docs changes → `(True, "")`
- None inputs → `(False, "invalid")` (fail-soft)

---

## Sub-task 2: merged_diff_library helpers

**File:** `runner/merged_diff_library.py` (new file)

Two pure functions that parse unified-diff text:

### `_frameworks(diff: str) -> list[str]`
Detect frameworks referenced in diff hunks by scanning import/require/use
statements and config filenames (pytest.ini, nuxt.config, package.json deps).

### `_changed_files(diff: str) -> list[str]`
Extract deduplicated, sorted file paths from `diff --git a/... b/...` headers.
Handle renames (`rename from`/`rename to`).

**Acceptance test** (`runner/tests/test_merged_diff_library.py`, minimum 8 cases):
- `_frameworks` detects `pytest` from `import pytest` in a hunk
- `_frameworks` detects `vue` from `<script setup>` or `import { ref } from 'vue'`
- `_frameworks` detects `prisma` from `prisma.schema` in changed files
- `_frameworks` returns `[]` for plain Python with no framework imports
- `_changed_files` parses standard `diff --git a/foo.py b/foo.py` → `["foo.py"]`
- `_changed_files` handles renames → includes both old and new paths
- `_changed_files` deduplicates and sorts output
- Both return `[]` on empty/None input (fail-soft)

---

## Sub-task 3: _extract_patterns_from_commit orchestrator

**File:** `runner/merged_diff_memory.py` (add function)
**Function:** `_extract_patterns_from_commit(repo: str, commit_hash: str) -> dict | None`

Single-commit processor that:
1. Runs `git show <hash>` to get diff
2. Calls `quality_gate` (stub/mock if not yet available)
3. Calls `_frameworks` and `_changed_files` (stub/mock if not yet available)
4. Calls existing `_extract_rules` on the diff
5. Returns `{commit_hash, rules, frameworks, files_changed}` or None if rejected

Uses optional-import pattern: if `learn_from_merges.quality_gate` or
`merged_diff_library` are not importable, skip those steps (always pass gate,
return empty lists). This makes it independently testable.

**Acceptance test** (`runner/tests/test_extract_patterns_from_commit.py`, minimum 8 cases):
- Returns dict with expected keys for a valid commit
- Returns None when quality_gate rejects (mocked)
- Populates `rules` from `_extract_rules` output
- Populates `frameworks` from `_frameworks` output (mocked)
- Populates `files_changed` from `_changed_files` output (mocked)
- Returns None for nonexistent commit hash (fail-soft)
- Returns `{..., rules: [], frameworks: [], files_changed: []}` when stubs are used
- Handles subprocess errors without raising (fail-soft)

---

## Sub-task 4: scan-to-enrichment pipeline

**File:** `runner/cowork_assemble.py` (extend existing)

Wire `merged_diff_scan.scan_project()` results into the enrichment prompt so
prior merge learnings are consulted during task execution. Currently the memos
are write-only — captured and indexed but never read back by the assembler.

1. In the enrichment section of `cowork_assemble.py`, call
   `merged_diff_scan.scan_project(project_id)` to retrieve recent memos
2. Format the top-5 most recent rules as a "Prior merge learnings" block
3. Append to `enriched_prompt` when available, skip silently when empty

**Acceptance test** (`runner/tests/test_merged_diff_assemble_integration.py`, minimum 8 cases):
- Enriched prompt includes "Prior merge learnings" header when memos exist
- Enriched prompt is unchanged when no memos exist
- Only top-5 rules are included (not all)
- Handles scan_project returning empty list
- Handles scan_project raising an exception (fail-soft: no crash, no learnings block)
- Memos from >30 days ago are excluded
- Rules are deduplicated across memos
- Works when CLAUDE_PROJECTS_ROOT is missing (fail-soft)
