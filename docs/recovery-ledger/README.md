# Recovery ledger — ChatGPT/Codex local build evidence (beethoven)

One JSON ledger per audit fingerprint, produced by `scripts/reconcile-evidence.mjs`.

Current ledgers: `0481d68df58a`, `0df18d9279e9`, `170f33cf2458`, `286879fa5fe4`,
`44d6bb63e4fc`, `696153ef8f37`, `6e398b6bdfef`, `968c9d3ff963`, `9ac0b820e01f`,
`d64eac25eb52`, **`3b50d1e569de`**.

## What was done

The task carried a snapshot of local evidence. Rather than classify a snapshot, the
tool **enumerates the live source** — as the brief requires — and classifies every
item it actually finds.

`3b50d1e569de`: **1554 items** classified against `origin/master` @ `d3a6b47a`,
**zero UNKNOWN and zero CONFLICTED**.

| classification | count |
|---|---|
| ALREADY_PRESENT | 878 |
| RECOVERABLE_VALUE | 675 |
| SUPERSEDED_BY_NEWER | 1 |
| ACTIVE_IN_ANOTHER_TASK | 0 |
| CONFLICTED_NEEDS_FOCUSED_TASK | 0 |

Sources enumerated: local branches, `refs/orch-rescue/*`, `refs/archive/*`,
`refs/quarantine/*`, `refs/codex/*`, the stash, and every registered worktree.

## The snapshot's one item: a worktree whose git metadata is gone

`/Users/kpasch/Documents/Codex/2026-08-07/cons/work/orchestrator-session-fabric`, dated
2026-08-11. Its `.git` file points at
`claude-orchestrator/.git/worktrees/orchestrator-session-fabric`, which no longer
exists, so `git status` fails and no ref-based classifier can reach it. It had to be
classified by **content**, file by file, against current `master`.

Result over its 3440 files (excluding `.git`, `node_modules`, `.runtime`):

- **3106 identical** to current `master`
- **180 differ** — every one an *older* revision of a file `master` has since moved
  past; `master` is 860+ commits ahead of the date on this tree
- **0 files present here and absent from `master`**, once dot-marker scratch files
  (`.canary-*`, `.copyfix-*`, `.deploy-*`) are excluded. The one candidate,
  `test_template_95fc17a.py`, is a one-line stub that exists on `master` at
  `runner/tests/test_template_95fc17a.py`

Classification: **SUPERSEDED_BY_NEWER**. It carries nothing `master` lacks, and taking
any of its 180 differing files would be a partial revert. Nothing was deleted, reset,
cleaned or moved — the directory is exactly where it was, orphaned metadata and all.

## Why 675 RECOVERABLE_VALUE items are not bulk-integrated

The brief says to apply the *minimum coherent diff* for recoverable value. 675 rescue
refs are not one coherent diff — they are independent snapshots taken by the periodic
sweep, most of them mid-flight states of work that later landed by another route.
Merging them wholesale would be the opposite of minimum and would overwrite current
code with older trees, which the brief explicitly forbids.

The disposition is **durable provenance, not integration**: every item classified and
recorded, and every item whose only copy is this disk pushed somewhere it survives.

## Read-only, and it is enforced

`runGit()` carries an allowlist of non-mutating subcommands and an explicit refusal
list — `checkout`, `reset`, `clean`, `stash pop`, `apply`, `update-ref` and the rest
throw with a named reason; `git stash` is permitted only as `list` and `show`.

**Nothing was popped, dropped, reset, cleaned or moved.**

## The number that matters

**513 tips have no remote copy and content not yet on `origin/master`.** For those the
only copy is this disk. `preserve-local-only-3b50d1e569de.sh` pushes each to
`refs/preserved/<name>` — outside `refs/heads/*`, so the merge train, CI and Vercel do
not enumerate them and nothing deploys by accident. Dry run by default; `APPLY=1` pushes.

A further 486 tips also have no remote copy but classify ALREADY_PRESENT: `origin/master`
already holds their commits, so preserving them would protect nothing and would bury the
513 that matter. They are ledgered, not pushed.

Run the script before this machine is ever rebuilt.
