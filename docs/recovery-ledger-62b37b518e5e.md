# Recovery ledger — `62b37b518e5e`

Audit fingerprint: `62b37b518e5eae4bb61cfb88207cca9f4dbeb0432f4359588d151a25c02f54d7`
Task slug: `chatgpt-local-reconcile-beethoven-62b37b518e5e`
Base: `origin/master` · reconciled 2026-09-10

Per-item records: `docs/recovery-ledger-62b37b518e5e.json`, produced by the
repo's existing `scripts/reconcile-evidence.mjs`, whose git allowlist makes the
read-only guarantee enforced rather than promised. Nothing was popped, dropped,
reset or moved.

## Result

**4,620 evidence items classified, 0 UNKNOWN.** A further 131 were excluded up
front as orchestration artefacts (67) and run scaffolding (64).

| Classification | Count |
|---|---:|
| ALREADY_PRESENT | 3,550 |
| RECOVERABLE_VALUE | 1,069 |
| SUPERSEDED_BY_NEWER | 1 |
| CONFLICTED_NEEDS_FOCUSED_TASK | 0 |
| ACTIVE_IN_ANOTHER_TASK | 0 |

By kind: 3,535 rescue refs, 1,057 branches, 15 worktrees, 13 stashes.

The task prompt carried a 10-item snapshot; the live source was enumerated
instead, as the contract requires, which is why the count is three orders of
magnitude larger.

## The 10 items the prompt named

Each was also checked directly against `origin/master`, because "a live branch
carries it" is only reassuring if the branch is real and the content is still
absent from the base. All ten are owned by a live branch, so none was
re-applied here — duplicating work already represented by a branch is what the
coordination rule forbids.

### Six ChatGPT bridge artifacts in `_applied/`

| Artifact | Carrier branch | State |
|---|---|---|
| `…chatgpt-local-queue-bridge-20260811.zip` | `origin/chatgpt/chatgpt-local-queue-bridge-20260811-08111602` | 4 commits ahead; 12 files touched, 6 already identical on master |
| `…chatgpt-local-intake-receipt-safety-20260811.zip` | `origin/chatgpt/chatgpt-local-intake-receipt-safety-20260811-08111725` | 1 commit ahead; 2 files, none on master |
| `…operator-output-truth-session-fabric-20260812.patch` | `origin/chatgpt/operator-output-truth-session-fabric-20260812-08120203` | 1 commit ahead; 18 files, none on master |
| `…promotion-and-funnel-fixes-20260817.patch` | `origin/chatgpt/promotion-and-funnel-fixes-20260817-08171915` | 5 commits ahead; 10 files, none on master |
| `…promotion-funnel-and-prod-urls-20260817.patch` | `origin/chatgpt/promotion-funnel-and-prod-urls-20260817-08171936` | 6 commits ahead; 10 files, none on master |
| `…promotion-funnel-prod-urls-and-review-fixes-20260818.patch` | `origin/chatgpt/promotion-funnel-prod-urls-and-review-fixes-2026-08172022` | 7 commits ahead; 11 files, none on master |

Every branch exists on the remote and each `.result.txt` records a PR (the
queue-bridge one is PR #20). None is an ancestor of `origin/master`, so the work
is still outstanding — **classification: ACTIVE_IN_ANOTHER_TASK, disposition:
none, land it through the existing PRs.** The last three are successive
revisions of the same funnel work, so landing them in order matters; a
force-apply from the dropbox would have raced all three.

### Four Codex paths

- **`Codex/2026-08-07/cons/work/orchestrator-session-fabric`** — the prompt
  recorded `git metadata no longer resolves`, and that is still true: git
  reports `not a git repository: …/.git/worktrees/orchestrator-session-fabric`.
  The working files are on disk and untouched, and the sweep finds a live
  `agent/recover-codex-worktree-orchestrator-session-fabric` branch already
  carrying the recovery. **ACTIVE_IN_ANOTHER_TASK.**
- **`…/orchestrator-session-fabric-current`** — resolves (HEAD `59de85f2`) with
  four staged changes. Its one genuinely new path,
  `supabase/migrations/20260811160000_paused_host_release_guard_v2.sql`, **is
  already on `origin/master`** and present in `supabase/migrations/`.
  **ALREADY_PRESENT** — and worth stating explicitly, because a migration in the
  ledger with no file committed is the failure that has repeatedly turned
  production deploys red. It is not that failure; the file is there.
- **`Codex/2026-08-06/figu/work/orchestrator-visibility-remediation`** — dirty
  at HEAD `fbb735b3` with four modified files. Carried by a live
  `agent/recover-codex-worktree-orchestrator-visibility-remediation` branch.
  **ACTIVE_IN_ANOTHER_TASK.**
- **`…/cons/outputs/claude-orchestrator--operator-output-truth-session-fabric-20260812.patch`**
  — an 18-file patch, the same change as the `_applied` copy above; carried by
  `agent/codex-recover-operator-output-truth-patch-*` and the `chatgpt/` branch.
  **ACTIVE_IN_ANOTHER_TASK.**

## One thing this ledger does not claim

The sweep records `ACTIVE_IN_ANOTHER_TASK: 0` across all 4,620 items while the
ten items above are, demonstrably, each owned by a live branch — the classifier
labels the *branch* as the item holding value rather than marking the underlying
evidence as owned. That is a reporting artefact of `reconcile-evidence.mjs`, not
a claim that nothing is owned elsewhere, and the per-item dispositions above
were verified by hand against `origin/master` rather than read off the bucket.
Worth a focused look before that count is used as an input to anything.
