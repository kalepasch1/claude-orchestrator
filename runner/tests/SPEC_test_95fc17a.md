# SPEC — `test_template_95fc17a.py`

Implementation specification for the acceptance test of patch template
`95fc17a356b7`. Written so the test can be reconstructed from this file alone,
with no other context.

## 0. Resolving the two names in the original ask

The task said "commit 95fc17a356b7" and "the file at the repository root".
Both are misleading and cost prior attempts the whole task, so they are pinned
here:

- **`95fc17a356b7` is a patch-template id, not a git SHA.** `git show
  95fc17a356b7` fails with *ambiguous argument … unknown revision*. Template ids
  are 12 hex chars produced by `patch_templates._id()`; git SHAs in this repo are
  8 or 40. The patch that *implements* the template is commit **`76749e0c`**
  ("Add patch_templates.lookup() for template 95fc17a356b7 with failing-test-first
  coverage", 2026-08-02). Read that with `git show 76749e0c`.
- **The canonical file is `runner/tests/test_template_95fc17a.py`.** A 25-byte
  file of the same name exists at the repo root whose entire body is its own
  filename; it is the known junk artifact that `runner/write_guard.py` was
  written to prevent, has no docstring, and must not be used as the source of
  truth. This spec therefore lives next to the canonical test.

## 1. Purpose

Prove that `patch_templates` can resolve a stored template **back from its id**.

Before `76749e0c`, `patch_templates` wrote every built template to the
`knowledge` table with a fail-soft JSONL fallback at
`.runtime/patch_templates.jsonl`, but exposed no read path. Recovery and
transplant flows held a template id and had nothing to call. The patch adds
`patch_templates.lookup(template_id)`.

**Failing-test-first:** every case below must fail with `AttributeError:
module 'patch_templates' has no attribute 'lookup'` when run against the parent
of `76749e0c`, and pass at `76749e0c`.

## 2. Contract under test

`lookup(template_id) -> dict`

| Input | Result |
|---|---|
| `None`, `""`, whitespace-only | `{}` |
| id present in the JSONL fallback | that row; **newest matching entry wins** |
| id absent locally, present in `knowledge` | `{"template_id", "body", "title", "source": "db"}` |
| id present in both | the JSONL row; the DB is **not** queried |
| unknown id | `{}` |
| any error (missing file, corrupt lines, DB down) | `{}` — **never raises** |

Two properties are load-bearing and easy to lose in a rewrite:

- **Whitespace tolerance.** `lookup("  95fc17a356b7  ")` must hit; the id is
  `.strip()`ed before comparison.
- **Local-first precedence.** The JSONL store is authoritative when it has a
  match, because it is the store that survives a DB outage — the exact condition
  under which recovery flows run.

## 3. Imports

```python
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
```

No third-party packages. `unittest`, not `pytest` — the suite is run with
`python3 -m unittest`.

## 4. Module preamble (required, in this order)

```python
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ORCH_DB_URL", "")
os.environ.setdefault("ORCH_DB_ENABLED", "false")

import patch_templates as pt

TID = "95fc17a356b7"
```

The `sys.path` insert puts `runner/` on the path so `import patch_templates`
resolves flat, matching how the runner imports its own modules. The two env
defaults must be set **before** the import: `patch_templates` imports `db` at
module scope, and an unset DB URL is what keeps the suite offline.

## 5. Fixtures

There are no pytest fixtures and no database. Two mechanisms only:

1. **`tempfile.TemporaryDirectory()`** per test, holding a throwaway
   `patch_templates.jsonl`. Never write to the real `.runtime/` path — a test
   that pollutes the live fallback store changes runner behaviour.
2. **`unittest.mock.patch.object`**, two seams:
   - `patch.object(pt, "_fallback_path", return_value=<tmp path>)` — redirects
     the JSONL store. Point it at a **non-existent** path to simulate "no local
     store".
   - `patch.object(pt.db, "select", ...)` — with `return_value=[rows]` for a DB
     hit, `return_value=[]` for a miss, `side_effect=Exception(...)` for an
     outage, and `side_effect=AssertionError("db must not be queried")` to prove
     the DB was never consulted.

Helper, used by every JSONL case:

```python
def _jsonl(path, rows):
    with open(path, "w") as f:
        for row in rows:
            f.write((row if isinstance(row, str) else json.dumps(row)) + "\n")
```

Accepting raw strings as well as dicts is deliberate: it is how corrupt lines
are injected.

## 6. Arrangement, action, assertion

Every case follows the same three steps:

1. **Arrange** — open a temp dir; write a JSONL store with `_jsonl()` (or point
   `_fallback_path` at a missing file); enter the `patch.object` context(s).
2. **Act** — call `pt.lookup(...)` *inside* the patch context, assign to `row`.
3. **Assert** — *outside* the context, so a failure message is not muddied by an
   active mock.

## 7. Cases (14, grouped into five classes)

**`LookupContractTest`** — existence and the fail-soft contract.

1. `test_lookup_is_exposed` — `callable(getattr(pt, "lookup", None))`. This is
   the assertion that fails with `AttributeError` pre-patch.
2. `test_none_id_returns_empty_dict` — `pt.lookup(None) == {}`.
3. `test_empty_id_returns_empty_dict` — `""` and `"   "` both `== {}`.
4. `test_unknown_id_returns_empty_dict` — missing file + `db.select` raising;
   `pt.lookup("ffffffffffff") == {}`.
5. `test_never_raises_on_db_error` — `db.select` raising `RuntimeError("boom")`;
   `pt.lookup(TID) == {}`.

**`LookupJsonlFallbackTest`** — the local store.

6. `test_known_id_found_in_jsonl` — one row `{"ts": 1.0, "task": …,
   "template_id": TID, "body": f"PATCH TEMPLATE {TID}\nIntent: x"}`; assert
   `row["template_id"] == TID` and `TID in row["body"]`.
7. `test_newest_matching_entry_wins` — three rows (`ts` 1.0 `TID` "old body",
   2.0 other, 3.0 `TID` "new body"); assert `row["body"] == "new body"`.
8. `test_corrupt_lines_are_skipped` — `"{not valid json"`, `""`, a valid row
   `"survives corruption"`, `"[1, 2, 3]"`; assert the valid row is returned.
   The `[1, 2, 3]` line matters: it parses as JSON but is not a dict, so it
   pins the `isinstance(row, dict)` check, not just the `ValueError` catch.
9. `test_whitespace_around_id_is_tolerated` — `pt.lookup(f"  {TID}  ")` hits.

**`LookupDbFallbackTest`** — the knowledge table.

10. `test_db_row_returned_when_file_missing` — missing file; `db.select`
    returns `[{"title": …, "body": f"PATCH TEMPLATE {TID}\nIntent: y"}]`;
    assert `row["template_id"] == TID` and `TID in row["body"]`.
11. `test_jsonl_hit_takes_precedence_over_db` — JSONL row `"local wins"` **and**
    `db.select` with `side_effect=AssertionError("db must not be queried")`;
    assert `row["body"] == "local wins"`. The assertion is the mock: if the DB
    is touched, the test errors.
12. `test_empty_db_result_returns_empty_dict` — missing file, `db.select`
    returns `[]`; result `== {}`.

**`StoreLookupRoundtripTest`** — the property that makes this useful.

13. `test_store_then_lookup_roundtrip` — with `db.insert` **and** `db.select`
    both raising (full DB outage), call `pt.build(task)`, then `pt._store(task,
    tid, body)`, then `pt.lookup(tid)`; assert the returned `template_id` and
    `body` equal what `build()` produced. This is the end-to-end claim: a
    template written during an outage is retrievable during that same outage.
    Use `task = {"slug": "canary-claude-27-slice-3", "project_id": "beethoven",
    "prompt": "write failing test for patch template lookup then verify"}`.
14. `test_template_id_is_stable_12_hex` — `pt._id(task) == pt._id(dict(task))`
    and matches `r"^[0-9a-f]{12}$"`. Ids must be deterministic or lookup by id
    is meaningless.

## 8. Precise failing assertion

The single assertion that fails if `76749e0c` is not applied:

```python
self.assertTrue(callable(getattr(pt, "lookup", None)),
                "patch_templates.lookup(template_id) must exist")
```

`getattr(..., None)` rather than a bare attribute access is intentional: it
produces the readable message above instead of a raw `AttributeError`, so the
failure names the missing contract rather than the traceback.

## 9. Running it

```bash
python3 -m unittest runner.tests.test_template_95fc17a -v
```

Expected: `Ran 14 tests … OK`, offline, in well under a second.

## 10. Registry obligation

`runner/tests/PATCH_TEMPLATE_REGISTRY.md` maps each template hash to its owner
module and acceptance test. The row for this one already exists:

| Template id | Owner module | Acceptance test |
|---|---|---|
| 95fc17a356b7 | `runner/patch_templates.py` (`lookup`) | `runner/tests/test_template_95fc17a.py` |

Any new hash-scoped test must add its row in the same commit.
