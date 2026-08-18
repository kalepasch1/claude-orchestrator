# Recovery ledger — ChatGPT/Codex local build evidence (beethoven)

One JSON ledger per audit fingerprint, produced by `scripts/reconcile-evidence.mjs`.

Current ledgers: `0481d68df58a`, `0df18d9279e9`, `170f33cf2458`, `286879fa5fe4`,
`44d6bb63e4fc`, `696153ef8f37`, `6e398b6bdfef`, `968c9d3ff963`, `9ac0b820e01f`,
<<<<<<< HEAD
`d64eac25eb52`, **`84fc83c513d9`**.
=======
`d64eac25eb52`, **`179a43b4d07a`**.
>>>>>>> agent/dropbox-pareto-life-goal-autonomy-stack-p4-household-legal-doc-updater-notificat

## What was done

The task carried a snapshot of 370 `refs/orch-rescue/*` items. Rather than classify a
snapshot, the tool **enumerates the live source** — as the brief requires — and
classifies every item it actually finds. The live count is four times the snapshot's.

<<<<<<< HEAD
`84fc83c513d9`: **1560 items** classified against `origin/master` @ `d3a6b47a`,
=======
`179a43b4d07a`: **1556 items** classified against `origin/master` @ `d3a6b47a`,
>>>>>>> agent/dropbox-pareto-life-goal-autonomy-stack-p4-household-legal-doc-updater-notificat
**zero UNKNOWN and zero CONFLICTED**.

| classification | count |
|---|---|
<<<<<<< HEAD
| ALREADY_PRESENT | 879 |
| RECOVERABLE_VALUE | 680 |
=======
| ALREADY_PRESENT | 880 |
| RECOVERABLE_VALUE | 675 |
>>>>>>> agent/dropbox-pareto-life-goal-autonomy-stack-p4-household-legal-doc-updater-notificat
| SUPERSEDED_BY_NEWER | 1 |
| ACTIVE_IN_ANOTHER_TASK | 0 |
| CONFLICTED_NEEDS_FOCUSED_TASK | 0 |

<<<<<<< HEAD
## The tool itself was the recoverable value
=======
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
>>>>>>> agent/dropbox-pareto-life-goal-autonomy-stack-p4-household-legal-doc-updater-notificat

The classifier on `master` was 485 lines. An unmerged agent branch carried a 911-line
version dated a day later, adding `--preserve-plan`, external-worktree and
ChatGPT-bridge classifiers, and a 33-case test file. Every function name in the older
copy is present in the newer one, so it is a strict superset, not a divergence — it was
adopted here rather than reimplemented, and `node --test scripts/reconcile-evidence.test.mjs`
passes.

<<<<<<< HEAD
## The bug that adopting it exposed

The run printed:

> 518 item(s) have NO remote copy — the only copy is on this disk

and then generated a preservation plan covering **11** of them. `buildPreservationPlan`
filtered on `kind === 'branch'`, so the other 507 — rescue, archive and quarantine refs —
were reported as at-risk in one breath and silently dropped from the rescue plan in the
next. That is the worst shape a safety tool can take: it names the risk and then does not
cover it, so the count reads as reassurance.

A sweep ref is the *most* at-risk kind of evidence in this repository. It exists
precisely because the work never got a branch. Excluding it inverted the tool's own
warning.

Fixed here: the plan now covers every ref-shaped item — branches, `refs/orch-rescue/*`,
`refs/archive/*`, `refs/quarantine/*`, `refs/codex/*`. Worktrees and stashes are still
excluded because they have no ref to push. Non-branch refs keep their source namespace
(`refs/preserved/orch-rescue/<name>`, not `refs/preserved/<name>`) so two kinds of
evidence that share a trailing name cannot collide on one preserved ref.

**Plan coverage went from 11 tips to 517.**

The test that asserted the old behaviour (`skips anything that is not a recoverable
branch`) is replaced by one that pins the new behaviour and one that pins the
no-collision property. 35 tests pass.

## Why 680 RECOVERABLE_VALUE items are not bulk-integrated

The brief says to apply the *minimum coherent diff*. 680 rescue refs are not one
coherent diff — they are independent periodic-sweep snapshots, most of them mid-flight
states of work that later landed by another route. Merging them wholesale would be the
opposite of minimum and would overwrite current code with older trees, which the brief
forbids. The disposition is durable provenance, not integration.
=======
A previous attempt at this fingerprint added `tools/reconcile-local-evidence.mjs`, a
second classifier alongside the existing `scripts/reconcile-evidence.mjs`. That is not
carried forward. Two classifiers to keep in step is exactly the duplication this
directory's earlier note warned about; the existing tool already resolves its base from
`--default-branch` and needs no fork.
>>>>>>> agent/dropbox-pareto-life-goal-autonomy-stack-p4-household-legal-doc-updater-notificat

## Read-only, and it is enforced

`runGit()` carries an allowlist of non-mutating subcommands and an explicit refusal
list — `checkout`, `reset`, `clean`, `stash pop`, `apply`, `update-ref` and the rest
throw with a named reason; `git stash` is permitted only as `list` and `show`.

**Nothing was popped, dropped, reset, cleaned or moved.** The working tree the snapshot
names is still dirty, with the same file count it had before.

## The number that matters

<<<<<<< HEAD
**517 tips have no remote copy.** `preserve-local-only-84fc83c513d9.sh` pushes each to
`refs/preserved/<name>` — outside `refs/heads/*`, so the merge train, CI and Vercel do
not enumerate them and nothing deploys by accident. Dry run by default; `APPLY=1` pushes.

Run it before this machine is ever rebuilt.
=======
**515 tips have no remote copy and content not yet on `origin/master`.**
`preserve-local-only-179a43b4d07a.sh` pushes each to `refs/preserved/<name>` — outside
`refs/heads/*`, so the merge train, CI and Vercel do not enumerate them and nothing
deploys by accident. Dry run by default; `APPLY=1` pushes.

A further 486 tips also have no remote copy but classify ALREADY_PRESENT: `origin/master`
already holds their commits, so preserving them would protect nothing and would bury the
515 that matter. They are ledgered, not pushed.
>>>>>>> agent/dropbox-pareto-life-goal-autonomy-stack-p4-household-legal-doc-updater-notificat
