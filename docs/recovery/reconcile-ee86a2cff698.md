# ChatGPT/Codex local build-evidence reconciliation — beethoven (broken worktree + bridge artifacts)

- Audit fingerprint: `ee86a2cff698f1f6b7902e3670e20a536916b2c23e29ca374cfc8711bfebca7d`
- Task: `chatgpt-local-reconcile-beethoven-ee86a2cff698`
- Evidence: one broken Codex git worktree and two ChatGPT-bridge artifacts (read-only; nothing deleted, reset, cleaned, popped or moved)
- Items enumerated from the live source: **3**
- UNKNOWN items: **0**

## Classification summary

| Classification | Count |
|---|---|
| SUPERSEDED_BY_NEWER | 1 |
| ACTIVE_IN_ANOTHER_TASK | 2 |
| RECOVERABLE_VALUE | 0 |

## The two bridge artifacts already shipped

Both zips were applied by the bridge and pushed. Their content is on origin as open PRs, so
re-applying them here would duplicate work already represented by a remote branch:

| Artifact | Branch | PR | Size |
|---|---|---|---|
| `...chatgpt-local-queue-bridge-20260811.zip` | `chatgpt/chatgpt-local-queue-bridge-20260811-08111602` | #20 | 12 files, +1081 |
| `...chatgpt-local-intake-receipt-safety-20260811.zip` | `chatgpt/chatgpt-local-intake-receipt-safety-20260811-08111725` | #21 | 2 files, +111 |

Both are still OPEN and unmerged into `master`. That is worth stating plainly: the artifacts are
safe, but the work is not landed. Queued as `beethoven-followup-land-open-chatgpt-bridge-prs`.

## The broken worktree held nothing

`/Users/kpasch/Documents/Codex/2026-08-07/cons/work/orchestrator-session-fabric` — 29 MB, 3440
files, `.git` gitlink pointing at an admin dir that no longer exists.

All 3440 files were enumerated against `origin/master`. 147 paths are absent from it, and every
one is a dotfile, a log, or garbage. The only three source-shaped paths are:

- `runner/utils/auto_branch_cleanup.py` — **empty, 0 bytes**
- `runner/utils/backlog_batch.py` — **empty, 0 bytes**
- `test_template_95fc17a.py` — contains only the string `test_template_95fc17a.py`

Those are artifacts of a malformed patch application, not lost work. There was nothing to recover.
The directory was left exactly where it is.

## What was fixed instead

The evidence item is itself an instance of a defect nothing in the fleet could see.

A worktree's `.git` is a file reading `gitdir: <admin dir>`. When that admin dir is deleted but the
working directory survives, the worktree becomes invisible to everything that would clean it up:

- `git worktree prune` only removes admin dirs whose WORKING directory is gone — here it is the
  other way round, so prune finds nothing and reports success.
- `gc_repo` calls `_recently_active`, which cannot read a broken gitlink and fails CLOSED
  ("recent"). Correct as a safety default, but it means an orphan reads as freshly active
  forever and is never collected.
- any `git` command run inside the directory dies with `fatal: not a git repository`, which is
  usually how these get discovered — something unrelated breaks and the orphan turns up while
  chasing it.

`runner/worktree_gc.py` gains `is_orphaned_worktree`, `orphaned_worktrees` and
`report_orphaned_worktrees`. They **report only** — an orphan's working directory is often the
last surviving copy of whatever was being built when the admin dir went, so it stays evidence
until a human says otherwise. Detection fails closed toward *not* an orphan: a garbage `.git`, a
missing path or an ordinary checkout is never reported, because the only safe response to a false
positive here is to do nothing.

Relative gitdirs are resolved against the worktree, not the cwd — resolving against cwd would
report healthy slots as orphans depending on where the sweep happened to run from.

## Verification

- `runner/tests/test_orphaned_worktrees.py` — **15 passed**, including the state TRANSITION (a
  healthy worktree whose admin dir is then removed), relative gitdirs, garbage gitlinks, ordinary
  checkouts, duplicate collapsing, and never raising on a bad repo argument.
- Run against the real evidence path, detection returns `True` and names the missing gitdir.
- Worktree-suite regression: `origin/master` 10 failed / 190 passed; this branch 10 failed /
  203 passed. Identical failure count.

## Provenance

- SUPERSEDED_BY_NEWER (the broken worktree) -> nothing recoverable; the defect it exposed is fixed
  on branch `agent/chatgpt-local-reconcile-beethoven-ee86a2cff698` (this commit).
- ACTIVE_IN_ANOTHER_TASK (both bridge artifacts) -> origin PRs #20 and #21, plus a queued task to
  land them.
- Every evidence source remains exactly where it was.

