# Recovery ledger — beethoven — combined local ChatGPT/Codex evidence

- audit fingerprint: `5dc36bf5e0bed6f108545572d49189cbfbc558ee98ae1290254e2e125f7e5918`
- base: `origin/master`
- evidence items classified: **543**
- UNKNOWN remaining: **0**

Every rescue ref was treated as read-only. No ref, stash or worktree
was deleted, reset, cleaned, popped or moved by this reconciliation.

## Classification summary

| classification | count |
| --- | ---: |
| RECOVERABLE_VALUE | 55 |
| CONFLICTED_NEEDS_FOCUSED_TASK | 14 |
| ACTIVE_IN_ANOTHER_TASK | 25 |
| SUPERSEDED_BY_NEWER | 279 |
| ALREADY_PRESENT | 170 |

## Items needing follow-up

| ref | sha | class | files | disposition |
| --- | --- | --- | ---: | --- |
| `orch-rescue/20260803T000726-relfix-racefeed-07060650-slice-4` | `9c023d06b7` | RECOVERABLE_VALUE | 4 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260803T000752-relfix-racefeed-07060650-slice-4` | `5152ab956f` | RECOVERABLE_VALUE | 4 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260803T001521-relfix-racefeed-07060650-slice-4-ad00f1c9` | `ad00f1c964` | RECOVERABLE_VALUE | 4 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260805T145454-deployfix-beethoven-07190338-fix-and-verify-vercel-production-build-423c51ca` | `423c51ca9a` | RECOVERABLE_VALUE | 1 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260805T191227-cc-mutual-default-fund-1d7e8d9a` | `1d7e8d9a0f` | CONFLICTED_NEEDS_FOCUSED_TASK | 1993 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260805T191228-cc-solvency-passport-6138fffd` | `6138fffd67` | CONFLICTED_NEEDS_FOCUSED_TASK | 355 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260806T100003-improve-missing-branch-auto-creator-slice-3-locate-decomposition-event-handler-a-bedc007c` | `bedc007cc0` | RECOVERABLE_VALUE | 1 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260806T100004-improve-value-aware-test-routing-early-exit-r-slice-3-adapt-merged-patterns-65464532` | `6546453246` | RECOVERABLE_VALUE | 1 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260806T131026-improve-value-aware-test-routing-early-exit-r-slice-3-adapt-merged-patterns-d09561bf` | `d09561bff0` | CONFLICTED_NEEDS_FOCUSED_TASK | 1289 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260806T131034-5bee398fbf584c3252b3-57b674c5` | `57b674c557` | CONFLICTED_NEEDS_FOCUSED_TASK | 2583 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260806T161111-relfix-release-hold-deadlock-cowork-20260806-e9050616` | `e9050616be` | CONFLICTED_NEEDS_FOCUSED_TASK | 3 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260806T172735-dropbox-operator-gate-amendment-auto-ship-authoriz-slice-2-9225b0f5` | `9225b0f507` | RECOVERABLE_VALUE | 3 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260806T201809-improve-value-aware-test-routing-early-exit-r-slice-3-fix-broken-tests-ba304347` | `ba3043475f` | RECOVERABLE_VALUE | 2 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260806T202615-improve-value-aware-test-routing-early-exit-r-slice-3-fix-broken-tests-63cf225e` | `63cf225ebc` | RECOVERABLE_VALUE | 3 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260806T215726-unbounded-scan-window-class-audit-cowork-20260806-512f19be` | `512f19be82` | RECOVERABLE_VALUE | 5 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260806T221512-fix-compilation-types-4fb310c6` | `4fb310c6e6` | RECOVERABLE_VALUE | 14 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260806T224241-improve-upgrade-to-a-high-performance-database-slice-3-integrate-new-module-aa3c1231` | `aa3c123138` | RECOVERABLE_VALUE | 4 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260806T224945-relfix-racefeed-07060650-fix-typescript-and-build--slice-4-fix-missing-branch-7d9bd79d` | `7d9bd79d37` | CONFLICTED_NEEDS_FOCUSED_TASK | 2189 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260807T015247-dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-p4-releasetrain-vercel-9c79f8f6` | `9c79f8f60c` | CONFLICTED_NEEDS_FOCUSED_TASK | 1439 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260807T125256-orchestrator-visibility-remediation-15d8c552` | `15d8c55228` | RECOVERABLE_VALUE | 15 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260807T130647-orchestrator-visibility-remediation-a05140c3` | `a05140c32f` | RECOVERABLE_VALUE | 16 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260807T173615-claude-orchestrator-12001806` | `12001806df` | RECOVERABLE_VALUE | 2 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260807T220546-improve-automate-branch-management-slice-3-310c54b3` | `310c54b335` | CONFLICTED_NEEDS_FOCUSED_TASK | 1644 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260808T040916-improve-immediate-auto-merge-on-test-pass-low-r-slice-3-implement-test-completio-7bf524c4` | `7bf524c475` | CONFLICTED_NEEDS_FOCUSED_TASK | 256 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260808T184515-cade-mirror-negotiation-5d33743e` | `5d33743e80` | CONFLICTED_NEEDS_FOCUSED_TASK | 1786 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260808T184519-canary-claude-27-slice-3-update-tests-checks-analyze-patch-behavior-analyze-patc-a4a7ec82` | `a4a7ec82a3` | CONFLICTED_NEEDS_FOCUSED_TASK | 851 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260811T152527-orchestrator-session-fabric-current-364b3d7a` | `364b3d7a04` | RECOVERABLE_VALUE | 15 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260813T034449-orchestrator-session-fabric-current-7ba40cac` | `7ba40cacae` | RECOVERABLE_VALUE | 18 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260813T045320-reconcile-beethoven-55acd60c-ed040682` | `ed0406825f` | RECOVERABLE_VALUE | 18 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260813T063106-chatgpt-local-reconcile-beethoven-6c8911116873-36ff050f` | `36ff050f9d` | CONFLICTED_NEEDS_FOCUSED_TASK | 3 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260813T081746-chatgpt-local-reconcile-beethoven-e0945946bd0d-45fefc8b` | `45fefc8b78` | CONFLICTED_NEEDS_FOCUSED_TASK | 2 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260813T084725-fix-canonical-enqueue-trigger-regression-20260812-7bf01722` | `7bf017227d` | RECOVERABLE_VALUE | 2 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260813T085137-fix-canonical-enqueue-trigger-regression-20260812-cd80d50c` | `cd80d50c94` | RECOVERABLE_VALUE | 2 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260813T201101-pinned-express-814604f7` | `814604f710` | RECOVERABLE_VALUE | 1 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260813T201603-pinned-express-dcf328aa` | `dcf328aaa8` | RECOVERABLE_VALUE | 1 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260813T202224-pinned-express-739d0d24` | `739d0d249f` | RECOVERABLE_VALUE | 1 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260813T205213-dropbox-beethoven-audit-addendum-two-session-reconciliation-read-wit-group-5-3213f4fa` | `3213f4fa8f` | RECOVERABLE_VALUE | 2 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260813T213903-dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-3-speed-triage-routing-accelerators-p0-28c0982f` | `28c0982f84` | RECOVERABLE_VALUE | 1 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260813T233826-c27-minimal-680be7c7` | `680be7c71c` | RECOVERABLE_VALUE | 1 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260813T234327-c27-minimal-649efcae` | `649efcae3b` | RECOVERABLE_VALUE | 1 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260814T001818-canary-claude-27-slice-1-run-checks-90a1e704` | `90a1e70413` | RECOVERABLE_VALUE | 8 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260814T033735-competitive-scanner-5-55556b63` | `55556b63e6` | RECOVERABLE_VALUE | 3 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260814T034302-competitive-scanner-5-cbc66ea1` | `cbc66ea1ce` | RECOVERABLE_VALUE | 3 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260814T034919-competitive-scanner-5-1e6883f1` | `1e6883f136` | RECOVERABLE_VALUE | 3 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260814T040650-competitive-scanner-5-946f7445` | `946f744514` | RECOVERABLE_VALUE | 4 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260814T043640-backlog-batch-beethoven-a86bb21-recover-pinned-exp-slice-1-26b72d0b` | `26b72d0b1a` | RECOVERABLE_VALUE | 2 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260814T044159-backlog-batch-beethoven-a86bb21-recover-pinned-exp-slice-1-50dd28e3` | `50dd28e386` | RECOVERABLE_VALUE | 3 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260814T045028-dropbox-recover-lease-night-g1-95167518` | `951675184a` | RECOVERABLE_VALUE | 1 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260814T045028-improve-queue-prevent-live-runner-merge-conflicts-slice-1-74bf0115` | `74bf0115dd` | RECOVERABLE_VALUE | 1 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260814T045639-backlog-batch-beethoven-d3151d8-d2055a73` | `d2055a738b` | RECOVERABLE_VALUE | 1 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260814T045644-improve-queue-prevent-live-runner-merge-conflicts-slice-1-0e014e1e` | `0e014e1e71` | RECOVERABLE_VALUE | 1 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260814T050204-backlog-batch-beethoven-d3151d8-87d761c1` | `87d761c1ab` | RECOVERABLE_VALUE | 1 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260814T051247-improve-queue-prevent-live-runner-merge-conflicts-slice-1-2442bcd8` | `2442bcd81e` | RECOVERABLE_VALUE | 2 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260814T072712-leasenight-7071d96c` | `7071d96cf0` | RECOVERABLE_VALUE | 1 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260814T072717-wavec-p4-51a1a5e0` | `51a1a5e041` | RECOVERABLE_VALUE | 1 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `heads/agent/dropbox-hisanta-mastery-engine-grandma-rail-family-slice-2-clean-129448` | `358297faa1` | RECOVERABLE_VALUE | 11 | range diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `heads/agent/improve-missing-branch-auto-creator-slice-3-locate-decomposition-event-handler-a-clean-152441` | `dc65c5428c` | RECOVERABLE_VALUE | 4 | range diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `heads/agent/improve-value-aware-test-routing-early-exit-r-slice-3-fix-broken-tests-clean-151469` | `a9e98fc3c7` | RECOVERABLE_VALUE | 3 | range diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `heads/backlog-batch-illuminati-1d1b027` | `0abf5b6d4c` | RECOVERABLE_VALUE | 5 | range diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator` | `371ac7f487` | RECOVERABLE_VALUE | 339 | 339 untracked new file(s) with no tracked counterpart; review and land through an agent branch. Source left untouched. |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/backlog-batch-beethoven-22ee5bc-convention-conform-slice-2 8309febb` | `1eda33098a` | RECOVERABLE_VALUE | 2 | 2 uncommitted path(s); tracked diff applies to base. Recover via a new isolated worktree + agent branch. Source worktree left untouched. |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/backlog-batch-beethoven-22ee5bc-prompt-evolution-bandit-update-claude-interface 67280171` | `76d068867d` | RECOVERABLE_VALUE | 2 | 2 uncommitted path(s); tracked diff applies to base. Recover via a new isolated worktree + agent branch. Source worktree left untouched. |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/canary-claude-27-slice-3-adapt-prior-merged-patterns-extract-proven-diffs-extrac 15227eb7` | `ba57d64f0f` | RECOVERABLE_VALUE | 2 | 2 uncommitted path(s); tracked diff applies to base. Recover via a new isolated worktree + agent branch. Source worktree left untouched. |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/never-again-lane-daemon` | `9a14f09438` | RECOVERABLE_VALUE | 9 | 9 uncommitted path(s); tracked diff applies to base. Recover via a new isolated worktree + agent branch. Source worktree left untouched. |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/spine-types-x2` | `987e5280e7` | RECOVERABLE_VALUE | 1 | 1 untracked new file(s) with no tracked counterpart; review and land through an agent branch. Source left untouched. |
| `/Users/kpasch/Documents/Codex/2026-08-06/figu/work/orchestrator-visibility-remediation` | `fbb735b3cf` | RECOVERABLE_VALUE | 17 | 17 uncommitted path(s); tracked diff applies to base. Recover via a new isolated worktree + agent branch. Source worktree left untouched. |
| `/Users/kpasch/Documents/Codex/2026-08-07/cons/work/orchestrator-session-fabric-current` | `59de85f238` | RECOVERABLE_VALUE | 18 | 18 uncommitted path(s); tracked diff applies to base. Recover via a new isolated worktree + agent branch. Source worktree left untouched. |
| `/Users/kpasch/Documents/chatgpt-dropbox/_applied/20260812-020326--claude-orchestrator--operator-output-truth-session-fabric-20260812.patch` | `889cdfd161` | RECOVERABLE_VALUE | 18 | bridge marked this applied, but the patch still applies to origin/master -- the change never reached the default branch. Recover through an agent branch. |
| `/Users/kpasch/Documents/chatgpt-dropbox/_failed/20260807-085521--smarter--apparently-framework-merge.patch` | `6b8f95f50a` | CONFLICTED_NEEDS_FOCUSED_TASK | 68 | failed bridge artifact whose patch no longer applies; queue a focused follow-up rather than forcing an overwrite |

## Disposition rules applied

- `ALREADY_PRESENT` — reachable from base, patch-identical to base, or an
  empty sweep commit. No action.
- `SUPERSEDED_BY_NEWER` — every touched path was rewritten in base after the
  ref was cut. Newest implementation wins; no action.
- `ACTIVE_IN_ANOTHER_TASK` — the commit is contained in a live `agent/*`
  branch. Left to that task; not duplicated here.
- `RECOVERABLE_VALUE` — diff still applies. Recover through an isolated
  worktree and the normal agent-branch + merge-train path.
- `CONFLICTED_NEEDS_FOCUSED_TASK` — diff no longer applies. A focused
  follow-up is queued instead of forcing an overwrite.
