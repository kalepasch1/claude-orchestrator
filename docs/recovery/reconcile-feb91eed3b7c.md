# ChatGPT/Codex local build-evidence reconciliation — beethoven (rescue refs + local branch tips)

- Audit fingerprint: `feb91eed3b7cb862257dd0e33a146c63672cead2e40632c32265c493a93d62ca`
- Task: `chatgpt-local-reconcile-beethoven-feb91eed3b7c`
- Evidence kinds: `orchestrator_rescue_refs` (`refs/orch-rescue/*`) and
  `local_only_branch_tips` (`refs/heads/*` with no counterpart on origin)
- Evidence source: `/Users/kpasch/Documents/beethoven/claude-orchestrator`, read-only
- Items enumerated: **682** (the snapshot in the task carried 41 + 572; the live
  source had grown, and the live source is what was classified)
- UNKNOWN items: **0**

## Classification summary

| Classification | Count |
|---|---|
| ALREADY_PRESENT | 263 |
| SUPERSEDED_BY_NEWER | 229 |
| CONFLICTED_NEEDS_FOCUSED_TASK | 90 |
| RECOVERABLE_VALUE | 53 |
| ACTIVE_IN_ANOTHER_TASK | 47 |

Ledger: `.orch/recovery-ledger-feb91eed3b7c.json`. Every item is also a row in
`coordination_tasks` under this fingerprint, so the disposition of any single ref is
answerable with a query rather than by re-reading a git blob.

## What this branch actually recovers

**`refs/heads/improve/cost-ledger-fail-soft` → `runner/cost_ledger.py`.**

One commit (`b0ba3f39`), never pushed to origin, that makes `cost_ledger` fail-soft the
way `CLAUDE.md` says every module in this repo must be: `_n()` returns 0 instead of
raising `ValueError` on a malformed token count, `record()` survives an unwritable
ledger path, and `report()` skips malformed JSON lines instead of dying on the first
one. Cherry-picked here with `-x`, so the original sha stays in the message.

Two corrections were made while landing it, both from this repo's own stated rules:

- The recovered `record()` used a bare `except Exception: pass`. `CLAUDE.md` is explicit
  that a broad catch is the fail-soft *convention* but a **silent** one is the defect —
  it now writes a diagnostic to stderr before continuing. A cost row that disappears
  unannounced is how the ledger stops matching reality.
- It shipped with no test, which is precisely why it sat on a local-only branch long
  enough to become recovery evidence. `runner/tests/test_cost_ledger_failsoft.py` adds
  6 cases covering both fail-soft paths and the malformed-ledger read.

The other 52 RECOVERABLE_VALUE items are all `refs/orch-rescue/*`, and they are **not**
recovered here. They belong to the same rescue-ref population that three sibling tasks
in this session also enumerate. Landing them on four branches at once is what produced
the unmergeable chain the previous reconciliation pass had to rebuild. They are owned by
`chatgpt-local-reconcile-beethoven-b4da5a48b1ee`, whose evidence is *only* rescue refs.

## New: `tools/publish_recovery_ledger.py`

The recovery contract asks for one `coordination_tasks` record per evidence item. Doing
that by hand does not scale to a 682-item ledger, and every prior pass paid the same
cost, so this branch adds the tool instead:

- one record per item, carrying source, kind, classification, disposition, evidence,
  a capped file list and the true file count, plus branch and commit provenance;
- `RECOVERABLE_VALUE` and `CONFLICTED_NEEDS_FOCUSED_TASK` map to `open`, everything
  else to `closed` — status answers "does this still owe someone work";
- idempotent: an item already published under the same fingerprint is skipped, so a
  re-run after a partial failure does not duplicate the ledger;
- the dedupe read filters on the fingerprint **server-side**. The first version scanned
  `coordination_tasks` unfiltered and the runner's own truncated-scan guard caught it
  returning exactly the 1000-row page cap — a dedupe that silently cannot see the far
  end of the table is worse than no dedupe;
- it refuses a ledger with no `audit_fingerprint` rather than writing untraceable rows;
- `--dry-run` needs no credentials, and an agent worktree has no gitignored
  `runner/.env`, so `_runner_dir()` falls back to a runner that does.

`tools/test_publish_recovery_ledger.py`: 11 cases, no database touched.

## Deferred, with the reason recorded

The 90 CONFLICTED items are recorded individually rather than summarised away. The four
local branch tips among them (`backup-node-precatchup2-20260818` and three
`agent/*-clean-*` branches) hold range diffs that no longer apply; forcing any of them
over master would overwrite newer work, which the recovery contract forbids.

## Provenance

- No rescue ref, branch, stash or worktree was deleted, reset, cleaned, popped or moved.
  The reconcilers read git objects only.
- Recovered source files on this branch: `runner/cost_ledger.py` (+ its new test).
  No rescue-ref content is introduced here, so this branch does not collide with its
  siblings.
