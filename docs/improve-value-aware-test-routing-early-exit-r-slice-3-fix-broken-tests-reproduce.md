# Reproduction report — "fix broken tests" (value-aware test routing, slice 3)

**Verified against:** `origin/master@d90037dde74dbecd75b4e50f9fe55470641cd262`
**Run in:** an isolated worktree, `python3 -m pytest -q -p no:cacheprovider`
**Scope of this task:** reproduce and record. No production code was changed.

## Headline

**The two files the task names are not broken.** Both are green. The real breakage is
somewhere else, and it is worse than a failing test: `pytest tests/` never ran at all.

| Target named in the task | Command | Result |
|---|---|---|
| `tests/test_emit_task_log.py` | `pytest tests/test_emit_task_log.py -q` | **22 passed** |
| `tools/convention_lint.py` | `pytest tests/test_convention_lint.py -q` | **24 passed** |
| | `python3 -m tools.convention_lint` | exit 0 |

Anything downstream that was queued on the premise "these two are failing" should be
re-checked against this SHA before it runs.

## What is actually broken

### 1. `pytest tests/` aborts during collection and runs nothing

```
ERROR tests/test_gifting_protocol.py
ERROR tests/test_kindness_mint.py
ERROR tests/test_school_mode.py
!!!!!!!!!!!!!!!!!!! Interrupted: 3 errors during collection !!!!!!!!!!!!!!!!!!!!
1564 tests collected, 3 errors in 1.56s
```

First traceback:

```
tests/test_school_mode.py:5: in <module>
    from hisanta.contracts.family import CoppaConsent
E     File ".../hisanta/contracts/family.py", line 1
E       <<<<<<< HEAD
E       ^
E   SyntaxError: invalid syntax
```

Four tracked files carry unresolved git conflict markers: `hisanta/__init__.py`,
`hisanta/contracts/family.py`, `hisanta/hisanta/contracts/family.py`,
`hisanta/hisanta/mastery/engine.py`.

A collection abort is the worst failure mode automation has. pytest does not report
"3 broken files and 1564 results" — it reports *nothing*, so every other regression in
that run is invisible too. One bad merge silently switched the suite off.

**Status:** fixed under a sibling task
(`improve-implement-continuous-testing-automation-slice-4`), which resolves all four
files and adds `tests/test_no_unresolved_conflict_markers.py` so a conflict marker can
never reach master unnoticed again. Not re-done here.

### 2. `pytest tools/` — 27 failed, 97 passed

All 27 are in the two `merged_diff_memory` suites. They fall into three groups:

**(a) A real secret-detection miss — the only one with security weight.**

```
tools/test_merged_diff_memory.py::TestSecretDetection::test_has_secrets_private_key
    assert mdm._has_secrets("-----BEGIN PRIVATE KEY-----")
E   AssertionError: assert False
```

`_has_secrets` (tools/merged_diff_memory.py:30) requires a `:` or `=` on the line
before it will call a match a secret:

```python
if any(pat.search(line) for pat in SECRET_PATTERNS):
    # Heuristic: if the suspicious line has a value after ':' or '=', it's suspicious
    if ":" in line or "=" in line:
        return True
```

A PEM header has neither, so an armoured private key pasted into a diff is **not**
sanitised before being written to the merged-diff memory file. The same assertion
fails in `TestSecretDetectionComprehensive::test_has_secrets_pem_format` with a full
RSA block. This is a two-line fix (exempt PEM headers from the punctuation heuristic)
and deserves its own task rather than being smuggled into a reproduce-only slice.

**(b) Tests that shell out to `git checkout master` — environment, not code.**

```
E   subprocess.CalledProcessError: Command '['git', 'checkout', 'master']'
    returned non-zero exit status 1.
```

Affects ~20 of the 27. Agent work runs in a worktree under `{repo}-wt/{slug}`, and
`master` is checked out in the main clone, so git refuses the checkout. These tests
assume they own the repository. They should build a scratch repo in `tmp_path`
instead of touching the real one — until then they cannot pass in the environment
the fleet actually runs in.

**(c) One permission test that assumes a non-root, restrictive umask.**

```
tools/..._comprehensive.py::TestErrorHandling::test_write_memory_file_permission_error
E   PermissionError: Permission denied
```

### 3. `pytest runner/tests -k approval` — 24 failed, 339 passed

Pre-existing, and unrelated to `runner/approval_push.py` (which has zero conflict
markers on this SHA and compiles clean). Recorded here so the next agent does not
attribute them to an approval-push conflict that no longer exists.

## Recommended follow-ups

1. **Fix `_has_secrets` for PEM headers.** Smallest real bug, highest stakes: a
   private key currently survives sanitisation into the memory file.
2. **Make the `merged_diff_memory` git tests hermetic** (`tmp_path` scratch repo, no
   `git checkout` in the ambient clone). This is what makes `pytest tools/` runnable
   inside an agent worktree at all.
3. **Re-verify any queued task premised on `test_emit_task_log.py` or
   `convention_lint.py` failing.** They do not, at this SHA.
