# Release pipeline recovery — 2026-08-06

Record of what was diagnosed and fixed on 2026-08-06, after verified production
deploys stopped entirely for 17 days. Written because the repository had no
account of it, and the next agent to touch `release_train.py` needs this context
before changing anything there.

## The outage

Verified deploys per week climbed 1 → 24 → 98 → 151 through July, then dropped to
**0 for 17 days starting 2026-07-27**. Throughput upstream looked healthy the
whole time: tasks kept reaching DONE. Nothing alerted, because every failure mode
below fails *silently* — the distinguishing symptom of this incident is not error
volume but the absence of any signal at all.

## Root cause 1 — release-hold deadlock

A red gate self-heals by queueing one fix task. The planner then decomposes that
task into a DAG of 30–40 sub-tasks sharing the slug prefix.
`_open_release_fix_tasks` keyed the hold on `updated_at`, so any churning
sub-task renewed the 180-minute window indefinitely. `_hold_for_open_fix`
returned early on every cycle for the copy/qa/build/refresh gates — without
writing a release row or emitting a log line.

**Fixed** with a per-lineage budget measured from the *oldest* task in the
lineage, capped by `ORCH_RELEASE_FIX_HOLD_MAX_H`.

## Root cause 2 — merge-train scan-window starvation

`_pick_cards()` scanned the newest 3,000 of 238,177 approved cards. The train
stamps `decided_by` on everything it touches, so a card that was not merged
immediately aged out of the window and became invisible **permanently**.

**Fixed** by scanning oldest-first as well as newest-first.

## Root cause 3 — non-fast-forward production push

STAGING was pushed to the remote production branch with no prior fetch or
integrate, so the push was rejected. This is also why **42% of tasks marked
MERGED had commits that do not exist on origin** — the work never left one
machine's local checkout.

## Root cause 4 — MERGED written without reachability

A populated `artifact_commit` column proves that a string was written. It does
not prove the commit exists, or that it reached the production branch.

**Fixed** by gating the MERGED transition on `git merge-base --is-ancestor`.

## Root cause 5 — stale-host self-policing

A host far enough behind is, by definition, running code that predates the guard
intended to stop it. Self-policing cannot work in that direction.

**Fixed** by moving enforcement to a database trigger.

## Root cause 6 — auto-resolve silently discarding branch work

6 of 59 auto-resolved merges dropped branch-original edits across 28 files —
including, notably, the fixes for silent work loss themselves.

## The amplifier

`recover-missing-branch-*` tasks ask an agent to recreate a patch from a branch
that no longer exists. With no diff to work from they produce nothing, were
marked MERGED anyway, and the cycle repeats. **2,450 of the 9,918 no-code tasks
came from this loop.**

## The common thread

Every one of the six causes above is a silent early-return: a code path that
declines to act and writes no row, no log, and no metric. The pipeline did not
report failure for 17 days because no stage considered "I did nothing this pass"
worth recording. When changing any gate in `release_train.py` or the merge train,
the operative rule is that **a pass which does nothing must say why**.
