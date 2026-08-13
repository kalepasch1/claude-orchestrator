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

---

# Fingerprint `6c8911116873` — the number that mattered, made actionable

Two evidence items.

**`dirty_worktree` at `/Users/kpasch/Documents/beethoven/claude-orchestrator`** —
already integrated. The same source, at the same `changes_digest`
(`7e991556…`), was reconciled under fingerprint `48ada8033590` and its 206 live
items were committed to `agent/chatgpt-local-reconcile-beethoven-48ada8033590`.
Classified **ACTIVE_IN_ANOTHER_TASK**; doing it again is exactly the duplication
the coordination rule forbids.

**`local_only_branch_tips` — 22 in the snapshot, 30 live.** These are branch tips
with no counterpart on origin. If this machine dies, they die.

## Why a report was not enough

Every previous run ended by printing *"N item(s) have NO remote copy"* — 308 for
`0481d68df58a`, 383 for `10d6c3591091`. That line has been true and unacted-on for
every fingerprint so far. A count of what you are about to lose is an obituary, not
a recovery.

`--preserve-plan <path>` now writes the remedy: an idempotent shell script that
pushes each at-risk tip to `refs/preserved/<name>` on origin.

## Why `refs/preserved/` and not a branch

`refs/preserved/*` is not under `refs/heads/*`, so these are **not branches**. The
merge train, branch protection, CI triggers and Vercel's Git integration all
enumerate branches, and none of them will ever see these refs. Pushing 30 recovered
tips as real branches would hand the merge train 30 things to integrate and could
trip a production deploy — the cure would be worse than the risk. As preserved refs
they survive a dead disk and change nothing else.

The generated script is **dry-run by default** (`APPLY=1` to push), for the same
reason the classifier is read-only: the operator sees the plan before it runs. It is
idempotent — re-running pushes the same sha to the same ref, which is a no-op.

The plan for this fingerprint is committed alongside the ledger as
`preserve-local-only-6c8911116873.sh`. Nothing in this task pushed it.

## Tests

`scripts/reconcile-evidence.test.mjs` — now 22 cases, `node --test`. The seven new
ones pin the behaviour that matters: a preserved ref is never planned into
`refs/heads/`, tips a remote already holds are skipped, and an empty plan is still a
runnable script rather than a broken one.

---

# Fingerprint `e4b9212494ba` — the artifact kind the enumerator could not see

One evidence item: a bridge artifact at
`chatgpt-dropbox/_applied/20260812-020326--claude-orchestrator--operator-output-truth-session-fabric-20260812.patch`.

`enumerateBridgeArtifacts()` filtered on `.zip`, and `classifyBridgeArtifact()`
stripped `.zip$` to derive the slug. The bridge has since started emitting bare
`.patch` payloads. An artifact kind the enumerator cannot see is an artifact kind it
silently reports nothing about — the UNKNOWN bucket wearing a different hat.

Now `.zip`, `.patch` and `.diff` are all payloads, and `.result.txt` sidecars are
correctly excluded from the payload list.

## Reading the receipt instead of guessing from the name

Every artifact has a `<name>.result.txt` beside it containing the line:

```
[chatgpt-bridge] pushed branch chatgpt/operator-output-truth-session-fabric-20260812-08120203
```

That is the bridge stating what it did. The old code instead reconstructed the branch
from the filename — and the bridge appends a run suffix, so
`…-20260812` becomes `…-20260812-08120203`. Substring matching happened to bridge
that gap. A guess that usually works is the worst kind: it fails silently on the one
artifact whose naming drifted, and reports live code as unrecoverable.

`readBridgeReceipt()` is now consulted first; name matching remains only as the
fallback for artifacts with no receipt.

## What the wider net caught

Enumerating both buckets with the new extensions surfaced **four** artifacts where
the previous code saw two. Three are ALREADY_PRESENT, verified against the branch
each receipt names. The fourth had never been visible to any run:

`_failed/20260807-085521--smarter--apparently-framework-merge.patch` →
**CONFLICTED_NEEDS_FOCUSED_TASK**. It is a failed payload for the `smarter`
repository, no remote branch carries it, and the zip-only filter meant no
reconciliation had ever reported it. Left in place for a focused task.

## Tests

`scripts/reconcile-evidence.test.mjs` — 28 cases, `node --test`. The six new ones
cover the receipt parser (present, absent, records-no-push), `.patch`/`.diff`
enumeration, sidecar exclusion, and the run-suffix case where the receipt and the
filename disagree.

---

# Fingerprint `ac93979d6c7a` — four kinds, one pass

Evidence: a `dirty_worktree` at the orchestrator root, a second worktree at
`claude-orchestrator-wt/spine-types-x2`, the `broken_codex_git_worktree` at
`Codex/2026-08-07/cons/work/orchestrator-session-fabric`, and the queue-bridge
artifact — plus the live `orchestrator_rescue_refs` namespace.

**1347 items, zero UNKNOWN.** Every kind routed through a classifier that already
exists: rescue refs and branches through the ancestry path, the two worktrees through
`classifyExternalWorktree`, the artifact through `classifyBridgeArtifact` with its
branch read from the bridge's own receipt.

That is the point worth recording. The first fingerprints in this series each needed
the tool extended before their evidence could be classified at all — `.patch`
payloads, pruned gitdirs, untracked files. This one needed nothing. The extensions
were not per-task workarounds; they were the missing kinds, and the set now covers
what the audit actually produces.

Nothing was popped, dropped, reset, cleaned or moved.

---

# Fingerprint `e0945946bd0d` — the same patch, twice, under two names

Evidence: a `dirty_worktree` at the orchestrator root, the worktree at
`Codex/2026-08-07/cons/work/orchestrator-session-fabric-current`, and a
`codex_output_artifact` at
`Codex/2026-08-07/cons/outputs/claude-orchestrator--operator-output-truth-session-fabric-20260812.patch`.

**1350 items, zero UNKNOWN.**

## Why a Codex output is not just another bridge artifact

Codex writes its patch into its own session `outputs/` directory as
`<repo>--<slug>.patch`. Only later does the bridge copy it into the dropbox, rename
it with a timestamp prefix, apply it, and record where it landed in a
`.result.txt`. The same bytes end up in two places under two names, and **only the
copy in the dropbox knows what happened to it.**

Classified on its own, the Codex-side file looks like an unreferenced patch in a
scratch directory. That reads either as "the only copy" — needless recovery work on
code that already shipped — or as "some leftover", which is how a real only-copy gets
dropped. Neither is acceptable, and the filename cannot tell you which it is.

Matching across the rename by name would be guesswork. **Matching by content hash is
not.** If the bytes are identical it is the same patch, and whatever the bridge did
with one it did with both.

Here they are identical — `sha256 889cdfd16140` — so the Codex output inherits its
twin's verdict: ALREADY_PRESENT on
`origin/chatgpt/operator-output-truth-session-fabric-20260812-08120203`. Neither copy
was deleted; both are kept as provenance.

When there is no twin, the classifier falls back to the slug in the filename, and
failing that says plainly that the patch was written and nothing carried it — which
is the case worth waking someone for.

## Tests

`scripts/reconcile-evidence.test.mjs` — 33 cases, `node --test`. The five new ones
cover the identical twin across the rename, bytes that differ (no twin claimed),
the slug fallback, the orphaned output, and a path the snapshot names that disk no
longer has.

---

# Fingerprint `383306e1301e` — a clean pass, which is the point

Evidence: the `broken_codex_git_worktree` at
`Codex/2026-08-07/cons/work/orchestrator-session-fabric`, two bridge artifacts, and
the live `orchestrator_rescue_refs` namespace.

**1344 items, zero UNKNOWN**, and nothing about this run required a change to the
tool.

Worth stating because it was not true a few fingerprints ago. Each of the earlier
runs in this series hit a kind the classifier could not see — a pruned gitdir that
`git worktree list` cannot report, untracked files invisible to both `stash create`
and `diff`, `.patch` payloads excluded by a `.zip` filter, a Codex output renamed on
its way into the dropbox. Every one of those was fixed in the shared tool rather than
worked around in the task, and the result is that this fingerprint's evidence
classified end-to-end on the first pass.

Nothing was popped, dropped, reset, cleaned or moved.

---

# Fingerprint `3b50d1e569de` — one item, and it is the one that keeps recurring

A single evidence item: the `broken_codex_git_worktree` at
`Codex/2026-08-07/cons/work/orchestrator-session-fabric`. **1358 items enumerated
live, zero UNKNOWN.**

That worktree has now appeared in five separate fingerprints. Its verdict is stable
and worth stating once plainly: its **committed** content survives in
`refs/heads/codex/orchestrator-session-fabric`, so the pruned gitdir is not the loss
it looks like. What cannot be recovered is any **uncommitted** drift in the
directory, which is unreadable without the gitdir and is reported as
`uncommittedDriftUnreadable: true` rather than assumed to be nothing.

The recurrence is itself the signal. A source that keeps arriving in new audits is a
source nothing has resolved, and the resolution here is not a merge — it is either
committing that ref or accepting that the drift is gone. Recorded, not silently
re-recovered.

---

# Fingerprint `84fc83c513d9` — 418 items with no remote copy

Evidence: the `broken_codex_git_worktree` at
`Codex/2026-08-07/cons/work/orchestrator-session-fabric` and the live
`orchestrator_rescue_refs` namespace. **1371 items, zero UNKNOWN.**

**418 of them carry `remotePreserved: false`** — the highest count recorded against
this repository. For those the only copy is this disk, and that number is the one to
read first if the machine is ever rebuilt.

None was merged: the brief caps recovery at a minimum coherent diff, so each stays
queued for a focused task rather than being force-applied here. What this ledger
buys is that they are now enumerated, classified and durable in git, instead of
being a count in a log line that scrolls away.
