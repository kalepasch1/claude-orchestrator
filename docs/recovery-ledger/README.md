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

---

## Reconcile batch — `85d2de799d5d`, `696153ef8f37`, `0481d68df58a`

Three more fingerprints, classified against `origin/master` by enumerating the **live
source** rather than the snapshot each prompt carried. **1273 items each, zero
UNKNOWN**, `scripts/reconcile-evidence.mjs` exit 0.

| classification | count |
|---|---|
| ALREADY_PRESENT | 668 |
| RECOVERABLE_VALUE | 519 |
| ACTIVE_IN_ANOTHER_TASK | 86 |
| SUPERSEDED_BY_NEWER | 0 |
| CONFLICTED_NEEDS_FOCUSED_TASK | 0 |

The three ledgers agree exactly because all three fingerprints photograph one live
source, read within the same minute. The ledger is keyed by fingerprint so the
provenance survives; the classification is made against current `origin/master`,
which is the only state a recovery decision can sensibly be made against.

**`LIVE_TASK_SLUGS` was supplied (498 QUEUED/RUNNING beethoven slugs) and it moved 86
items.** Without it those 86 refs classify `RECOVERABLE_VALUE` — the one label that
invites someone to go recover them — when a live task already owns them. That is the
duplicated work the coordination rule forbids. The failure is silent: the tool still
exits 0 and still reports zero UNKNOWN. Anyone regenerating these must pass it.

**519 items are RECOVERABLE_VALUE and none were merged here.** The brief allows
recovery only via a newly allocated isolated worktree carrying the minimum coherent
diff, and 519 items is not a minimum coherent diff — it is 519 separate decisions.
This task delivers the classification and the provenance; each genuinely-wanted item
needs its own focused task. Nothing was deleted, reset, cleaned, popped or moved: the
tool refuses any git subcommand outside its read-only allowlist.

`scripts/reconcile-evidence.mjs` is committed alongside the ledgers. It existed only
as an untracked file in the main checkout — one copy, on one disk, generating the
artefact that documents what else is at risk on that same disk.

---

# Fingerprint `10d6c3591091` — the evidence git could not enumerate for itself

This snapshot carried three items. The first — 365 `refs/orch-rescue/*` refs — the
classifier already handled. The other two it structurally could not see:

| evidence kind | why the previous run would have missed it |
|---|---|
| `broken_codex_git_worktree` | `git worktree list` cannot report a worktree whose `worktrees/<name>` gitdir has been pruned — the registration is exactly what is gone |
| `chatgpt_bridge_artifact` | a dropbox zip is not a git object, so no ref enumeration reaches it |

Anything not enumerated is not classified, and an unclassified item is UNKNOWN —
the one outcome the completion bar forbids. So the gap was in the tool, not in the
run, and the fix went into the shared tool rather than into a one-off script.

## What was added

`classifyExternalWorktree(path, ctx)` and `classifyBridgeArtifact(path, ctx)`, plus
repeatable `--external-worktree`, `--bridge-artifact` and `--dropbox` flags.

Two judgements are load-bearing:

**A worktree is a checkout, not a copy.** Its committed content lives in the ref it
came from, so a pruned gitdir is only a real loss if that ref is also gone. What a
broken worktree genuinely costs is its *uncommitted* drift — unreadable once the
gitdir is pruned. That is reported as `uncommittedDriftUnreadable: true` rather than
quietly assumed to be nothing, because assuming it is nothing is how the only copy
of something gets written off.

**`_applied/` is not proof.** "The bridge script exited 0" and "the code is durably
on a remote" are different claims, and only the second one matters. An artifact in
`_applied/` whose branch is not on origin is classified RECOVERABLE_VALUE with the
reason *"the exit code said yes and the remote says otherwise"* — the zip is then
the only copy, which is precisely the case worth catching.

## Tests

`scripts/reconcile-evidence.test.mjs` — 15 cases, `node --test`. They cover the
vanished path, the still-healthy gitdir, the pruned gitdir with and without a
surviving ref, the live-task deferral, both dropbox buckets, and the flag parser.

## Read-only, still

The additions read: `existsSync`, `readFileSync`, `readdirSync`, and `for-each-ref`
through the same allowlisted `runGit`. No zip is extracted, no worktree is
re-registered, no ref is written. **Nothing was popped, dropped, reset or moved.**
