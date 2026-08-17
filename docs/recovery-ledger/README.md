# Recovery ledger — ChatGPT/Codex local build evidence (beethoven)

One JSON ledger per audit fingerprint, produced by `scripts/reconcile-evidence.mjs`.

Current ledgers: `0481d68df58a`, `0df18d9279e9`, `170f33cf2458`, `286879fa5fe4`,
`44d6bb63e4fc`, `696153ef8f37`, `6e398b6bdfef`, `968c9d3ff963`, `9ac0b820e01f`,
`d64eac25eb52`, **`179a43b4d07a`**.

## What was done

The task carried a snapshot of local evidence. Rather than classify a snapshot, the
tool **enumerates the live source** — as the brief requires — and classifies every
item it actually finds.

`179a43b4d07a`: **1556 items** classified against `origin/master` @ `d3a6b47a`,
**zero UNKNOWN and zero CONFLICTED**.

| classification | count |
|---|---|
| ALREADY_PRESENT | 880 |
| RECOVERABLE_VALUE | 675 |
| SUPERSEDED_BY_NEWER | 1 |
| ACTIVE_IN_ANOTHER_TASK | 0 |
| CONFLICTED_NEEDS_FOCUSED_TASK | 0 |

## The snapshot's item: the repository's own dirty working tree

`master` @ `8a166025`, 56 changed paths, sampled as `docs/decisions/ADR-*.md`. `8a166025`
is an ancestor of current `origin/master`, so the committed base is ALREADY_PRESENT and
the only remaining value is what is *untracked*.

Enumerating the live tree rather than the snapshot: **15 untracked `docs/decisions/ADR-*.md`
files**, none of them on `master`. Those are integrated here — copied, never moved, as a
purely additive 15-file diff.

**What was deliberately left out**, because "minimum coherent diff" is a constraint and
not a formality:

- `mcp/package-lock.json`, `packages/spine/package-lock.json`,
  `packages/beethoven-contracts/package-lock.json` — committing lockfiles scraped out of
  a dirty tree is how a reconcile task turns into a dependency change nobody reviewed.
- Modified *tracked* files (`runner/runner.py`, `runner/test_new_module_config.py`) —
  these are another process's in-flight edits. The coordination rule forbids overwriting
  unrelated live work, and a reconcile task has no business committing it.
- The 520 untracked `intake/processed/*.md` records — already delivered under fingerprint
  `48ada8033590`. Duplicating them here would be the duplication the coordination rule
  exists to prevent.

## Reused, not reforked

A previous attempt at this fingerprint added `tools/reconcile-local-evidence.mjs`, a
second classifier alongside the existing `scripts/reconcile-evidence.mjs`. That is not
carried forward. Two classifiers to keep in step is exactly the duplication this
directory's earlier note warned about; the existing tool already resolves its base from
`--default-branch` and needs no fork.

## Read-only, and it is enforced

`runGit()` carries an allowlist of non-mutating subcommands and an explicit refusal
list — `checkout`, `reset`, `clean`, `stash pop`, `apply`, `update-ref` and the rest
throw with a named reason; `git stash` is permitted only as `list` and `show`.

**Nothing was popped, dropped, reset, cleaned or moved.** The working tree the snapshot
names is still dirty, with the same file count it had before.

## The number that matters

**515 tips have no remote copy and content not yet on `origin/master`.**
`preserve-local-only-179a43b4d07a.sh` pushes each to `refs/preserved/<name>` — outside
`refs/heads/*`, so the merge train, CI and Vercel do not enumerate them and nothing
deploys by accident. Dry run by default; `APPLY=1` pushes.

A further 486 tips also have no remote copy but classify ALREADY_PRESENT: `origin/master`
already holds their commits, so preserving them would protect nothing and would bury the
515 that matter. They are ledgered, not pushed.
