# Adjudication of the CONFLICTED rescue refs (ledger 8d0702cbd5aa)

Base: `origin/master` @ 8a2e2e16. Read-only against `refs/orch-rescue/*` —
nothing was deleted, reset or moved. Machine output:
`adjudicated-8d0702cbd5aa.json`. Tool: `runner/tools/adjudicate_conflicted_refs.py`
(23 unit tests, green).

## The headline

The task was queued as **222 conflicted refs**. The ledger at
`.orch/recovery-ledger-8d0702cbd5aa.json` holds **53** items classified
`CONFLICTED_NEEDS_FOCUSED_TASK`, spanning **15,303** (ref, path) pairs. After
per-file adjudication the real remaining job is **65 unique paths**.

| verdict | pairs | meaning |
|---|---:|---|
| `ABSENT_IN_SWEEP` | 15,127 | the sweep listed the path as a **deletion**; the ref holds no blob there |
| `DIVERGED` | 111 | swept blob never appeared on master and master has different content — the real queue |
| `IDENTICAL` | 29 | swept blob equals master's; already landed |
| `HISTORICAL` | 26 | swept blob is an earlier state of master's path; master moved on |
| `ABSENT_ON_BASE` | 6 | path missing from master entirely — safe pure recovery |
| `MALFORMED` | 12 | not a path at all |

## Why 15,127 of 15,303 evaporated

**A recovery ledger's `files` list is a diff against the sweep's parent, not a
manifest of the sweep's tree.** It therefore contains deletions. A single ref
(`20260816T230458-safe-edit`, 685 files) swept a working tree checked out on a
different branch, so almost every path it "touched" it touched by *not having
it*. `git ls-tree <ref> -- <path>` returns nothing for those: there is no blob
to recover, ever.

The first pass of this tool called them MALFORMED, which was wrong and
alarming. They now get their own terminal verdict. This is the single most
important correction in this pass: **the conflicted namespace looked ~85x
bigger than it is because a deletion and a conflict were being counted the
same way.**

## The 12 genuinely malformed entries

Confirmed the artifacts the task warned about. Caught and skipped rather than
created:

- `unittest.main()` — an assertion line captured as a filename
- 11 entries that are whole source files quoted into a single string, e.g.
  `"runner/utils/auto_branch_cleanup.py\nimport os\nENABLED = ..."`

`is_malformed()` rejects anything containing `( ) = < > * ? | " '`, tabs,
newlines, double spaces, leading `/` or `-`, or surrounding whitespace. Nine
unit tests cover it, including both artifact shapes above.

## Recovered (5 files, `--recover-absent`)

Absent from master, non-noise, newest ref wins:

- `docs/recovery-ledger/383306e1301e.json`
- `docs/recovery-ledger/3b50d1e569de.json`
- `docs/recovery-ledger/e0945946bd0d.json`
- `docs/recovery-ledger/e4b9212494ba.json`

Four recovery ledgers from earlier reconciliations that were never committed —
the evidence trail for passes whose conclusions are otherwise unreproducible.

The sixth `ABSENT_ON_BASE` path, `tests/runner_modules.py`, is **deliberately
not** in this commit. It is the same file follow-up `c54c216bc5d3` recovers from
branch tip `a9e98fc3`, and landing identical content from two branches is how
the merge train gets an avoidable conflict. That task owns it; this one defers
to it. (Same reasoning the task prompt gives for adjudicating `b7fb78ad`
alongside the overlapping tips.)

## The 65 paths still needing per-hunk review

Machine list: `needs_human_review` in the JSON, with the ref and sha each came
from. By subsystem: `runner` 42, `web` 39, `scripts` 12, `docs` 6, `hisanta` 4,
`tests` 4, `tools` 3, `packages` 1 (pair counts; 65 unique paths).

Three of them are already resolved by sibling follow-ups landing in parallel and
should not be re-adjudicated here:

- `tools/convention_lint.py` — one hunk ported forward in `c54c216bc5d3`
- `tests/test_db_connectivity.py` — deferred there with a named reason
- `runner/{runner,slo_controller,benchmark_redlines,expert_corps,foulkon_sync}.py`
  — adjudicated in `b7fb78ad` and in `c54c216bc5d3`; master is newer on all of
  them, and replaying the sweep side would strip the `lane_guard`
  single-instance lock added after the legal_docket 14-copy incident.

The remainder are queued as batched follow-ups: `--out` groups recoveries by
first path segment so related files land in one commit rather than 65.

## Re-running

```bash
python3 runner/tools/adjudicate_conflicted_refs.py \
  --repo . --base origin/master \
  --ledger .orch/recovery-ledger-8d0702cbd5aa.json \
  --out docs/recovery-ledger/adjudicated-8d0702cbd5aa.json \
  --recover-absent
```

`--recover-absent` only ever creates paths that do not already exist on disk,
so a rerun is a no-op and an operator edit is never clobbered.
