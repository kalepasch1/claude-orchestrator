# Recovery ledger — ChatGPT/Codex local build evidence (beethoven)

One JSON ledger per audit fingerprint, produced by `scripts/reconcile-evidence.mjs`:
`6e398b6bdfef.json`, `d64eac25eb52.json`, `286879fa5fe4.json`, `44d6bb63e4fc.json`.

## What was done

The task carried a snapshot of local evidence. Rather than classify a snapshot, the
tool **enumerates the live source** — as the brief requires — and classifies every
item it actually finds.

**1099–1104 items** classified against `origin/master`, **zero UNKNOWN and zero
CONFLICTED in every ledger**. The count drifts by a few between runs because the
repository genuinely changed in the minutes between them — which is the same fact
the fingerprints report, visible a second way.

Representative counts (`6e398b6bdfef`):

| classification | count |
|---|---|
| ALREADY_PRESENT | 596 |
| RECOVERABLE_VALUE | 447 |
| ACTIVE_IN_ANOTHER_TASK | 56 |
| SUPERSEDED_BY_NEWER | 0 |
| CONFLICTED_NEEDS_FOCUSED_TASK | 0 |

Sources enumerated: 251 local branches, 5145 rescue/archive/orch-rescue/codex refs,
the stash, and every registered worktree.

## Reused, not reforked

The classifier is the same `scripts/reconcile-evidence.mjs` written for the
`tomorrow` reconcile tasks, **generalised rather than copied**. It previously
hard-coded `origin/main`; beethoven's default is `master`, and guessing wrong there
would have classified every ref against a branch that does not exist and reported
the entire repository as recoverable — a confidently useless answer. It now resolves
the default branch from `--default-branch`, else the `origin/HEAD` symref, else the
two conventional names, and **refuses to run** if none resolves.

That change belongs in the shared tool. Forking a beethoven-specific copy would have
left two classifiers to keep in step, which is the duplication the coordination rule
exists to prevent.

## Read-only, and it is enforced

`runGit()` carries an allowlist of non-mutating subcommands and an explicit refusal
list — `checkout`, `reset`, `clean`, `stash pop`, `apply`, `update-ref` and the rest
throw with a named reason; `git stash` is permitted only as `list` and `show`.

**Nothing was popped, dropped, reset, cleaned or moved.**

## The number that matters

**308 items have no remote copy.** For those, the only copy is this working
directory. They carry `remotePreserved: false` in the ledger and are the first thing
to look at if this machine is ever rebuilt.

Note the 56 `ACTIVE_IN_ANOTHER_TASK` items: those are already represented by a live
orchestrator task and are deliberately **not** touched here, per the coordination
rule against duplicating queued work.

## What is deliberately NOT done

No `RECOVERABLE_VALUE` item was merged. The brief permits recovery only via a newly
allocated isolated worktree carrying the minimum coherent diff, and 447 items is not
a minimum coherent diff — it is 447 separate decisions. This task delivers the
classification and the provenance; each genuinely-wanted item needs its own focused
task, which is the same rule the brief applies to conflicts.

## Regenerating

```bash
LIVE_TASK_SLUGS="slug-a,slug-b" node scripts/reconcile-evidence.mjs \
  --fingerprint <sha> --default-branch master \
  --json docs/recovery-ledger/<short>.json
```

Exit code is non-zero if any item is UNKNOWN — the completion bar, enforced.
