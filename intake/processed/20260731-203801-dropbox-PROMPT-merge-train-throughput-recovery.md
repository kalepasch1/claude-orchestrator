# Merge-Train Throughput Recovery — drive 581 skipped to merged (operator, 2026-07-31, CRITICAL)

project: beethoven

No app repo has had a prod promotion since Jul 28: merge_train reports "0 merged, 581 skipped,
10-13 project errors" every pass. Two isolation hard-errors are already fixed (commit 0348a0ef:
branch-attached/dirty integration slots now preserve + fall back to a fresh temp worktree —
verify this fix is live and the project-error count drops to ~0).

REMAINING WORK (this shard):
1. VISIBILITY: merge_train's summary hides WHY 581 branches skip. Add a per-reason breakdown to
   the summary JSON + log line (e.g. no_approved_card / verify_pending / waiting_window /
   already_merged_content / stale). A skip without a visible reason is how this sat broken since
   Jul 28 — silent-failure class.
2. RACEFEED SLOT: the racefeed integration worktree is dirty; PRESERVE its contents (branch or
   copy per the stash-rescue convention) then clear the slot so racefeed merges flow.
3. WAITING BACKLOG: "passed_waiting: 1, oldest_wait_age_s: 832159" — a branch has been passed-
   but-waiting 9.6 DAYS. Find the gate (approval card? release window? ORCH_PUSH_ON_RELEASE was
   false until today — now true). Drain everything whose only blocker was the release flag.
4. DRIVE TO GREEN: iterate passes until merged > 0 and the per-repo origin/master advances for
   tomorrow, smarter, illuminati, vigil, pareto-2080, apparently, racefeed. Each master push
   triggers the Vercel prod build — confirm new Production deployments appear per project.
5. REGRESSION TEST: add a test asserting a branch-attached clean slot self-detaches and a dirty
   slot falls back to temp (integration_runtime), plus a skip-reason accounting test.
All commits kalepasch1 <kalepasch@gmail.com>. Never force-push; never touch canonical checkouts.
