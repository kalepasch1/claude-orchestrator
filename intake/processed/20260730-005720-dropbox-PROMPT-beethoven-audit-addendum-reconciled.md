# beethoven: AUDIT ADDENDUM — two-session reconciliation (READ WITH PROMPT-beethoven-core-integrity-audit)

SUBMITTED-BY: kale@smrter.us (operator) 2026-07-30. Reconciles findings from TWO concurrent sessions on this repo (2026-07-29 overnight). Supersedes/constrains parts of the core integrity audit already in the queue.

WORKFLOW: governed_heavy

## A. DO-NOT-TOUCH LIST (verified deliberate — the subtraction work must NOT "fix" these)
A JOBS-dict-vs-`runner.py _SCHEDULE` audit already ran in the parallel session. These are unscheduled ON PURPOSE:
- `mergetrain` — `train-60` (merge_train.py) already covers it; running both caused duplicate retries.
- `actionexec` — strict subset of `autoexec` (scheduled every 60s, same function plus more).
- `editorial` — optional guarded-import module, unrelated to queue health.
- **`remotegc` — MUST STAY UNWIRED.** `workflow_guardrails.gc_remote_branches()` deletes `origin/agent/*` by AGE ONLY (`git push origin --delete`; `ORCH_REMOTE_BRANCH_GC_DRY_RUN=false` in .env) and — unlike local `branch_gc.py` — does NOT check task state, so it can delete the branch of a QUEUED/RUNNING/BLOCKED task. PREREQUISITE before any wiring: mirror `branch_gc.py`'s `terminal_slugs` gate (DONE/MERGED/QUARANTINED only). Irreversible external deletion = material.

## B. ALREADY FIXED + VERIFIED FIRING — DO NOT REDO
quarantine_gc (10min; 469 archived in first 25min), rca_engine (30min; new `duplicate-or-superseded` classifier, 369 bucketed), stuck_reaper, priority_scorer, sentinel `stash_drift_guard` (alert-only), restart-fleet.sh (real push-error surfacing + refuses to ship when checkout drifted off master, `FORCE_BRANCH=true` override), auto_conflict_resolver source-file guard, merge_train process_project restore, branch_lease fail-soft, Fable routing + hosted canary, 6 undefined-name/import bugs.

## C. STASH COUNT DISCREPANCY — resolve before triaging (do this FIRST in §5 of the core audit)
Parallel session measured **592** stashes; this session measured **315** on the same repo hours later, with `git reflog stash` also showing 315 (i.e. no evidence of drops on THIS machine). Hypotheses to test, in order: (1) the 592 count came from **Mac 2** (`Mandys-MacBook-Pro.local`), which holds its own independent stash pile — CHECK MAC 2's `git stash list | wc -l` before concluding anything; (2) a cleanup ran and the reflog expired; (3) miscount. **Do not begin bulk triage until this is explained** — if Mac 2 holds ~277 additional stashes, they must be triaged there too, and Mac 2's pile is currently invisible to every check run on Mac 1.

## D. TRIAGE RESULT ALREADY COMPUTED (Mac 1, read-only, 2026-07-30) — start from this, don't recompute
Of 315 stashes on Mac 1: **119 empty · 37 already-landed (content in HEAD) · 12 cleanly-recoverable · 120 conflicted (76 touch `runner/`)**. A vetted recovery script for the 12 exists at repo root: `recover_stashes.sh` (creates a `recovery/stashes-*` branch, one commit per stash + markdown ledger; never pops/drops; refuses to run dirty). The 120 conflicted are the real work — triage per §5 of the core audit, one at a time, best-version-wins where duplicates exist.
**Permanently lost (not recoverable, state it and move on):** 282 batches destroyed 2026-07-08→07-16 by the old destructive `stash push -u` in checkout_guard. Gone; not in any stash.

## E. NEW ROOT-CAUSE FIX LANDED THIS SESSION (verify it holds)
`sentinel.py` checkout_guard no longer STASHES protected-path changes — it now COMMITS them to `hotfix/sentinel-rescue-<ts>` and emits `hotfix-rescued`. Protected = `runner/`, `scripts/`, `web/server/`, any `.py`/`.sh`. This closes the mechanism that swallowed operator hotfixes twice in one night (including the fix for the resolver bug that was actively wiping improvements). Non-protected dirt still stashes. **Add a test asserting a dirty protected file survives a forced drift-restore as a commit, never a stash.**

## F. PUSH + MAC 2 (highest priority, blocks everything)
Five commits are local-only on Mac 1 (`9fa36cf6`, `28164826`, `a738b565`, `ea7d8621`, `bc05b70c`) — every critical fix from BOTH sessions. Until pushed, Mac 2 is running the broken resolver/train/lease code. Also: **SSH to Mac 2 failed every attempt this session** (falls back to queuing a `fleet_control` row) — diagnose (stale host key? asleep? wrong hostname?) and verify the fallback actually applied changes on Mac 2, because a silently-degraded second machine has been merging with the OLD whole-file resolver this whole time.
Security (non-blocking, do it soon): the `origin` remote URL has the GitHub PAT embedded (visible in `git remote -v`) — move to a credential helper / gh auth and scrub the token from remotes and any logs.

## G. Git identity
Both sessions used email `kalepasch@gmail.com` (the identity Vercel requires). Name has varied (`kalepasch1` vs `Kale Aaron Pasch`) — harmless, but standardize on the repo CLAUDE.md value (`kalepasch1`) going forward.
