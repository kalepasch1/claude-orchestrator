# Recovery ledger — beethoven — full local ChatGPT/Codex evidence sweep

- audit fingerprint: `165f6c7173b5d94520d186103651ae1146b51ab0aa61065abc4676767b5e5fa4`
- base: `origin/master`
- evidence items classified: **980**
- UNKNOWN remaining: **0**

Every rescue ref was treated as read-only. No ref, stash or worktree
was deleted, reset, cleaned, popped or moved by this reconciliation.

## Classification summary

| classification | count |
| --- | ---: |
| RECOVERABLE_VALUE | 213 |
| CONFLICTED_NEEDS_FOCUSED_TASK | 46 |
| ACTIVE_IN_ANOTHER_TASK | 25 |
| SUPERSEDED_BY_NEWER | 345 |
| ALREADY_PRESENT | 351 |

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
| `/Users/kpasch/Documents/Trojun-orchestrator-misclone-20260812` | `8f0a560798` | RECOVERABLE_VALUE | 2 | unregistered checkout holding 3 uncommitted path(s). Register the project or recover the work through an agent branch. Source repo is READ-ONLY — do not delete, reset or move it. |
| `/Users/kpasch/Documents/_Trojun_archived` | `e3b5c172f8` | RECOVERABLE_VALUE | 2 | unregistered checkout holding 223 uncommitted path(s). Register the project or recover the work through an agent branch. Source repo is READ-ONLY — do not delete, reset or move it. |
| `/Users/kpasch/Documents/darwinLife` | `1643c0afbc` | RECOVERABLE_VALUE | 2 | unregistered checkout holding 2 uncommitted path(s). Register the project or recover the work through an agent branch. Source repo is READ-ONLY — do not delete, reset or move it. |
| `/Users/kpasch/Documents/vinci` | `cef2b65f1a` | RECOVERABLE_VALUE | 2 | unregistered checkout holding 1 uncommitted path(s). Origin is not a registered project, so no executor or merge train will ever see it. Register the project or recover the work through an agent branch. Source repo is READ-ONLY — do not delete, reset or move it. |
| `heads/_rb` | `fcef8e0665` | RECOVERABLE_VALUE | 4 | diff still applies; route through the merge train |
| `heads/agent/approval-digest-batching` | `3a8977c911` | RECOVERABLE_VALUE | 5 | diff still applies; route through the merge train |
| `heads/agent/backlog-batch-beethoven-01b6ed7` | `acd0aba729` | RECOVERABLE_VALUE | 4 | diff still applies; route through the merge train |
| `heads/agent/backlog-batch-beethoven-13b64db` | `d686fcb8d0` | RECOVERABLE_VALUE | 2 | diff still applies; route through the merge train |
| `heads/agent/backlog-batch-beethoven-19236f3` | `6cc8c7c72c` | RECOVERABLE_VALUE | 2 | diff still applies; route through the merge train |
| `heads/agent/backlog-batch-beethoven-22ee5bc-convention-conform-slice-2` | `8309febb19` | RECOVERABLE_VALUE | 1 | diff still applies; route through the merge train |
| `heads/agent/backlog-batch-beethoven-22ee5bc-convention-conform-slice-5` | `87b8b8cb88` | RECOVERABLE_VALUE | 3 | diff still applies; route through the merge train |
| `heads/agent/backlog-batch-beethoven-22ee5bc-prompt-evolution-bandit-implement-performance-tr` | `7645d6312b` | RECOVERABLE_VALUE | 2 | diff still applies; route through the merge train |
| `heads/agent/backlog-batch-beethoven-22ee5bc-prompt-evolution-bandit-update-claude-interface-` | `880da0140e` | RECOVERABLE_VALUE | 1 | diff still applies; route through the merge train |
| `heads/agent/backlog-batch-beethoven-22ee5bc-recover-pinned-express-lane-validate-pinned-expr` | `fdf504f8df` | RECOVERABLE_VALUE | 1 | diff still applies; route through the merge train |
| `heads/agent/backlog-batch-beethoven-2863be9-merge-changes-slice-1` | `3509ab459f` | RECOVERABLE_VALUE | 1 | diff still applies; route through the merge train |
| `heads/agent/backlog-batch-beethoven-35584ad` | `c640efa68b` | RECOVERABLE_VALUE | 2 | diff still applies; route through the merge train |
| `heads/agent/backlog-batch-beethoven-45ec7f9` | `ae08d81f56` | RECOVERABLE_VALUE | 2 | diff still applies; route through the merge train |
| `heads/agent/backlog-batch-beethoven-59654f8` | `252b9e17b3` | RECOVERABLE_VALUE | 3 | diff still applies; route through the merge train |
| `heads/agent/backlog-batch-beethoven-63cf995-merged-diff-memory-add-test-and-validate-full-bu` | `648ea3cb44` | RECOVERABLE_VALUE | 1 | diff still applies; route through the merge train |
| `heads/agent/backlog-batch-beethoven-63cf995-recover-pinned-express-lane` | `eb3b9904a5` | RECOVERABLE_VALUE | 1 | diff still applies; route through the merge train |
| `heads/agent/backlog-batch-beethoven-7371e3f-add-bandit-prompt--slice-3-test-update-method-ed` | `f8b15f4ec0` | RECOVERABLE_VALUE | 1 | diff still applies; route through the merge train |
| `heads/agent/backlog-batch-beethoven-7371e3f-add-bandit-prompt--slice-4-add-decay-formula-to-` | `b6c7321f77` | RECOVERABLE_VALUE | 2 | diff still applies; route through the merge train |
| `heads/agent/backlog-batch-beethoven-7b53616-apply-orch-config-patch` | `49eb59a89a` | RECOVERABLE_VALUE | 2 | diff still applies; route through the merge train |
| `heads/agent/backlog-batch-beethoven-94401af` | `7a2985b0d2` | RECOVERABLE_VALUE | 3 | diff still applies; route through the merge train |
| `heads/agent/backlog-batch-beethoven-97e0e39-optimize-memory-slice-1` | `02c4559ffe` | RECOVERABLE_VALUE | 2 | diff still applies; route through the merge train |
| `heads/agent/backlog-batch-beethoven-97e0e39-optimize-memory-slice-2` | `c1fb3df807` | RECOVERABLE_VALUE | 2 | diff still applies; route through the merge train |
| `heads/agent/backlog-batch-beethoven-a661cf9` | `99fc0a28bd` | RECOVERABLE_VALUE | 2 | diff still applies; route through the merge train |
| `heads/agent/backlog-batch-beethoven-a86bb21-recover-convention-conformance-lints-finalize-li` | `8bc8fcb787` | RECOVERABLE_VALUE | 4 | diff still applies; route through the merge train |
| `heads/agent/backlog-batch-beethoven-a86bb21-recover-economic-scheduler-revenue-commit-fix-an` | `61f6e06e61` | RECOVERABLE_VALUE | 1 | diff still applies; route through the merge train |
| `heads/agent/backlog-batch-beethoven-a86bb21-recover-economic-scheduler-revenue-diagnose-sche` | `96c3ad1f1f` | RECOVERABLE_VALUE | 1 | diff still applies; route through the merge train |
| `heads/agent/backlog-batch-beethoven-a86bb21-recover-economic-scheduler-revenue-fix-economic-` | `1f80674662` | RECOVERABLE_VALUE | 2 | diff still applies; route through the merge train |
| `heads/agent/backlog-batch-beethoven-a86bb21-recover-economic-scheduler-revenue-fix-infinite-` | `1b37932900` | RECOVERABLE_VALUE | 2 | diff still applies; route through the merge train |
| `heads/agent/backlog-batch-beethoven-a86bb21-recover-pinned-express-lane-apply-fix-and-valida` | `5a7798eafa` | RECOVERABLE_VALUE | 1 | diff still applies; route through the merge train |
| `heads/agent/backlog-batch-beethoven-a86bb21-recover-remaining-stale-tasks-identify-and-fix-f` | `b47fc96264` | RECOVERABLE_VALUE | 3 | diff still applies; route through the merge train |
| `heads/agent/backlog-batch-beethoven-c7f3145` | `d42129c9ad` | RECOVERABLE_VALUE | 2 | diff still applies; route through the merge train |
| `heads/agent/backlog-batch-beethoven-c9a51c6-pinned-express-lane-repair` | `709dd83c95` | RECOVERABLE_VALUE | 1 | diff still applies; route through the merge train |
| `heads/agent/backlog-batch-beethoven-caafadd` | `8ae5112bef` | CONFLICTED_NEEDS_FOCUSED_TASK | 447 | diff no longer applies; queue a focused follow-up instead of forcing an overwrite |
| `heads/agent/backlog-batch-beethoven-ccacb00-commit-implementat-slice-1` | `77f30c54ba` | RECOVERABLE_VALUE | 1 | diff still applies; route through the merge train |
| `heads/agent/backlog-batch-beethoven-ccacb00-fix-failing-tests-fix-queue-velocity-pid-shelvin` | `358c1698b1` | RECOVERABLE_VALUE | 1 | diff still applies; route through the merge train |
| `heads/agent/backlog-batch-beethoven-ccacb00-fix-failing-tests-fix-remaining-failures` | `5b93eb7767` | RECOVERABLE_VALUE | 1 | diff still applies; route through the merge train |
| `heads/agent/backlog-batch-beethoven-ccacb00-fix-tests-fix-pid-integral-windup` | `e945ed2444` | RECOVERABLE_VALUE | 1 | diff still applies; route through the merge train |
| `heads/agent/backlog-batch-beethoven-ccacb00-repair-build-tools-check-build-tools` | `a8c2b06542` | RECOVERABLE_VALUE | 2 | diff still applies; route through the merge train |
| `heads/agent/backlog-batch-beethoven-ccacb00-repair-build-tools-install-python-deps` | `abc1498fd5` | RECOVERABLE_VALUE | 3 | diff still applies; route through the merge train |
| `heads/agent/backlog-batch-beethoven-ccacb00-repair-build-tools-verify-nodejs-npm` | `bcde784483` | RECOVERABLE_VALUE | 2 | diff still applies; route through the merge train |
| `heads/agent/backlog-batch-beethoven-cf3458a` | `f989872062` | RECOVERABLE_VALUE | 1 | diff still applies; route through the merge train |
| `heads/agent/backlog-batch-beethoven-d4ba22d-resolve-convention-conformance-lints` | `36b81f514b` | CONFLICTED_NEEDS_FOCUSED_TASK | 532 | diff no longer applies; queue a focused follow-up instead of forcing an overwrite |
| `heads/agent/backlog-batch-beethoven-e63dfee-apply-orch-config-consumption-patch` | `26a2e1e9d0` | RECOVERABLE_VALUE | 2 | diff still applies; route through the merge train |
| `heads/agent/backlog-batch-beethoven-e8afcee-inventory-clean-environment` | `09c8437237` | RECOVERABLE_VALUE | 2 | diff still applies; route through the merge train |
| `heads/agent/backlog-batch-beethoven-f298406` | `f2b7c5e961` | RECOVERABLE_VALUE | 2 | diff still applies; route through the merge train |
| `heads/agent/batch-mech-dropbox-beethoven-audit-addendum-two-session-recon-slice-1-extract-diff-template-3` | `8ae5112bef` | CONFLICTED_NEEDS_FOCUSED_TASK | 447 | diff no longer applies; queue a focused follow-up instead of forcing an overwrite |
| `heads/agent/cade-mirror-negotiation` | `8ae5112bef` | CONFLICTED_NEEDS_FOCUSED_TASK | 447 | diff no longer applies; queue a focused follow-up instead of forcing an overwrite |
| `heads/agent/canary-claude-27-slice-1-run-checks` | `b5360e4778` | RECOVERABLE_VALUE | 4 | diff still applies; route through the merge train |
| `heads/agent/canary-claude-27-slice-3-adapt-prior-merged-patterns-apply-adapted-patch-run-ful` | `8ae5112bef` | CONFLICTED_NEEDS_FOCUSED_TASK | 447 | diff no longer applies; queue a focused follow-up instead of forcing an overwrite |
| `heads/agent/canary-claude-27-slice-3-adapt-prior-merged-patterns-extract-proven-diffs-docume` | `da6c12b94f` | RECOVERABLE_VALUE | 1 | diff still applies; route through the merge train |
| `heads/agent/canary-claude-27-slice-3-update-tests-checks-implement-test-assertions-implement` | `8ae5112bef` | CONFLICTED_NEEDS_FOCUSED_TASK | 447 | diff no longer applies; queue a focused follow-up instead of forcing an overwrite |
| `heads/agent/canary-claude-27-slice-3-update-tests-checks-verify-test-passes` | `768e0fafc1` | RECOVERABLE_VALUE | 1 | diff still applies; route through the merge train |
| `heads/agent/canary-codex-17` | `f04b9a849d` | RECOVERABLE_VALUE | 2 | diff still applies; route through the merge train |
| `heads/agent/canary-codex-28-audit-prior-solutions-apply-pattern` | `426968d8c1` | RECOVERABLE_VALUE | 1 | diff still applies; route through the merge train |
| `heads/agent/canary-codex-28-consolidate-to-canonical-impl` | `744be85036` | RECOVERABLE_VALUE | 1 | diff still applies; route through the merge train |
| `heads/agent/canary-codex-28-locate-pricinggridreconstruction-duplica` | `a928fdbf87` | RECOVERABLE_VALUE | 3 | diff still applies; route through the merge train |
| `heads/agent/canary-codex-31-detect-expired-heartbeats` | `3b4fe52e3b` | RECOVERABLE_VALUE | 2 | diff still applies; route through the merge train |
| `heads/agent/canary-codex-39` | `17021e6b9f` | RECOVERABLE_VALUE | 5 | diff still applies; route through the merge train |
| `heads/agent/canary-codex-58-repo-setup-and-analysis-examine-canary-claude-33` | `2cff47e9ff` | RECOVERABLE_VALUE | 1 | diff still applies; route through the merge train |
| `heads/agent/canary-deepseek-6-run-full-canary-validation-run-e2e-tests` | `8ae5112bef` | CONFLICTED_NEEDS_FOCUSED_TASK | 447 | diff no longer applies; queue a focused follow-up instead of forcing an overwrite |
| `heads/agent/canary-deepseek-6-run-full-canary-validation-run-integration-tests-pass` | `b6c03cf922` | RECOVERABLE_VALUE | 3 | diff still applies; route through the merge train |
| `heads/agent/canary-deepseek-6-run-full-canary-validation-run-smoke-tests-pass-collect-failin` | `6009bd17ab` | RECOVERABLE_VALUE | 3 | diff still applies; route through the merge train |
| `heads/agent/canary-deepseek-6-run-full-canary-validation-run-smoke-tests-pass-fix-env-relate` | `8ae5112bef` | CONFLICTED_NEEDS_FOCUSED_TASK | 447 | diff no longer applies; queue a focused follow-up instead of forcing an overwrite |
| `heads/agent/canary-deepseek-6-run-full-canary-validation-run-smoke-tests-pass-fix-logic-rela` | `459a6197de` | RECOVERABLE_VALUE | 1 | diff still applies; route through the merge train |
| `heads/agent/canary-gemini-25-canary-gemini-25-metrics-create-gauge-set-gauge-to-0-on-validat` | `3a50e1a0a8` | RECOVERABLE_VALUE | 2 | diff still applies; route through the merge train |
| `heads/agent/canary-gemini-25-canary-gemini-25-metrics-http-server-setup` | `50d052a2a8` | RECOVERABLE_VALUE | 2 | diff still applies; route through the merge train |
| `heads/agent/canary-gemini-25-canary-gemini-25-request-parse-response-text` | `4fe783fb5b` | RECOVERABLE_VALUE | 2 | diff still applies; route through the merge train |
| `heads/agent/canary-gemini-25-canary-gemini-25-schedule` | `8c3efc7b15` | RECOVERABLE_VALUE | 3 | diff still applies; route through the merge train |
| `heads/agent/canary-gemini-25-canary-gemini-25-validate-add-validation-function-add-logging-i` | `8ae5112bef` | CONFLICTED_NEEDS_FOCUSED_TASK | 447 | diff no longer applies; queue a focused follow-up instead of forcing an overwrite |
| `heads/agent/canary-gemini-25-canary-gemini-25-validate-add-validation-function-implement-can` | `b80d9d06e9` | RECOVERABLE_VALUE | 2 | diff still applies; route through the merge train |
| `heads/agent/canary-gemini-25-canary-gemini-25-validate-add-validation-function-implement-val` | `1607cc957c` | RECOVERABLE_VALUE | 4 | diff still applies; route through the merge train |
| `heads/agent/canary-gemini-25-canary-gemini-25-validate-create-pytest-test-script-add-canary-` | `ec8aba94ea` | RECOVERABLE_VALUE | 1 | diff still applies; route through the merge train |
| `heads/agent/canary-gemini-25-commit-and-test` | `8ae5112bef` | CONFLICTED_NEEDS_FOCUSED_TASK | 447 | diff no longer applies; queue a focused follow-up instead of forcing an overwrite |
| `heads/agent/canary-gemini-25-recreate-smallest-patch` | `905ca6435a` | RECOVERABLE_VALUE | 4 | diff still applies; route through the merge train |
| `heads/agent/canary-gemini-pro-9-remove-duplicate-pricing-minimal-patch` | `02df7fec56` | RECOVERABLE_VALUE | 2 | diff still applies; route through the merge train |
| `heads/agent/canary-ollama-2-2-slice-5` | `eca9a9cb14` | CONFLICTED_NEEDS_FOCUSED_TASK | 412 | diff no longer applies; queue a focused follow-up instead of forcing an overwrite |
| `heads/agent/canary-xai-6` | `2a387ef26e` | CONFLICTED_NEEDS_FOCUSED_TASK | 5 | diff no longer applies; queue a focused follow-up instead of forcing an overwrite |
| `heads/agent/canary-xai-6-build-and-test` | `de7ff517ee` | RECOVERABLE_VALUE | 2 | diff still applies; route through the merge train |
| `heads/agent/canary-xai-6-build-test` | `8ae5112bef` | CONFLICTED_NEEDS_FOCUSED_TASK | 447 | diff no longer applies; queue a focused follow-up instead of forcing an overwrite |
| `heads/agent/chatgpt-local-reconcile-beethoven-10d6c3591091` | `bd54b80484` | RECOVERABLE_VALUE | 5 | diff still applies; route through the merge train |
| `heads/agent/chatgpt-local-reconcile-beethoven-215fba971ab9` | `a08611553b` | RECOVERABLE_VALUE | 8 | diff still applies; route through the merge train |
| `heads/agent/chatgpt-local-reconcile-beethoven-383306e1301e` | `d0ecb81c68` | RECOVERABLE_VALUE | 11 | diff still applies; route through the merge train |
| `heads/agent/chatgpt-local-reconcile-beethoven-3b50d1e569de` | `4ecfa8aa75` | RECOVERABLE_VALUE | 12 | diff still applies; route through the merge train |
| `heads/agent/chatgpt-local-reconcile-beethoven-48ada8033590` | `da633fc032` | RECOVERABLE_VALUE | 207 | diff still applies; route through the merge train |
| `heads/agent/chatgpt-local-reconcile-beethoven-4d83819ff744` | `6bde391bc8` | RECOVERABLE_VALUE | 9 | diff still applies; route through the merge train |
| `heads/agent/chatgpt-local-reconcile-beethoven-55acd60c79b1` | `1493349de1` | RECOVERABLE_VALUE | 18 | diff still applies; route through the merge train |
| `heads/agent/chatgpt-local-reconcile-beethoven-5e30d0e05126` | `b92e024851` | RECOVERABLE_VALUE | 13 | diff still applies; route through the merge train |
| `heads/agent/chatgpt-local-reconcile-beethoven-6c8911116873` | `84703647b1` | RECOVERABLE_VALUE | 7 | diff still applies; route through the merge train |
| `heads/agent/chatgpt-local-reconcile-beethoven-797668765dad` | `13d795918b` | RECOVERABLE_VALUE | 8 | diff still applies; route through the merge train |
| `heads/agent/chatgpt-local-reconcile-beethoven-7b6f925e1e7a` | `ada00069f7` | RECOVERABLE_VALUE | 19 | diff still applies; route through the merge train |
| `heads/agent/chatgpt-local-reconcile-beethoven-84fc83c513d9` | `239ec52800` | RECOVERABLE_VALUE | 13 | diff still applies; route through the merge train |
| `heads/agent/chatgpt-local-reconcile-beethoven-85d2de799d5d` | `e77e4616b2` | RECOVERABLE_VALUE | 3 | diff still applies; route through the merge train |
| `heads/agent/chatgpt-local-reconcile-beethoven-ab0a05980686` | `307c36efac` | RECOVERABLE_VALUE | 13 | diff still applies; route through the merge train |
| `heads/agent/chatgpt-local-reconcile-beethoven-ac93979d6c7a` | `8ff9c5f9e9` | RECOVERABLE_VALUE | 9 | diff still applies; route through the merge train |
| `heads/agent/chatgpt-local-reconcile-beethoven-e0945946bd0d` | `633e1610b3` | RECOVERABLE_VALUE | 10 | diff still applies; route through the merge train |
| `heads/agent/chatgpt-local-reconcile-beethoven-e4b9212494ba` | `1da71dac94` | RECOVERABLE_VALUE | 8 | diff still applies; route through the merge train |
| `heads/agent/chatgpt-local-reconcile-beethoven-fa5a31393f8a` | `e1dd6770b9` | CONFLICTED_NEEDS_FOCUSED_TASK | 417 | diff no longer applies; queue a focused follow-up instead of forcing an overwrite |
| `heads/agent/codex-recover-operator-output-truth-patch-7db8cf82` | `5dedfe700a` | RECOVERABLE_VALUE | 18 | diff still applies; route through the merge train |
| `heads/agent/contracts-smarter` | `8ae5112bef` | CONFLICTED_NEEDS_FOCUSED_TASK | 447 | diff no longer applies; queue a focused follow-up instead of forcing an overwrite |
| `heads/agent/copyfix-beethoven-07180848-slice-3` | `e1b5ee5495` | RECOVERABLE_VALUE | 1 | diff still applies; route through the merge train |
| `heads/agent/done-to-merged-is-the-new-bottleneck-cowork-20260806` | `4c2e490fed` | RECOVERABLE_VALUE | 4 | diff still applies; route through the merge train |
| `heads/agent/dropbox-beethoven-audit-addendum-two-session-recon-slice-5-test-and-commit` | `f45b96b682` | RECOVERABLE_VALUE | 4 | diff still applies; route through the merge train |
| `heads/agent/dropbox-beethoven-audit-addendum-two-session-reconciliation-read-wit-group-3` | `b2d51515de` | RECOVERABLE_VALUE | 4 | diff still applies; route through the merge train |
| `heads/agent/dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-1-never-again-lane-daemon-immune-system-p0-recovered` | `ac8d276847` | RECOVERABLE_VALUE | 18 | diff still applies; route through the merge train |
| `heads/agent/dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-3-speed-triage-routing-accelerators-p0` | `0a175f1569` | RECOVERABLE_VALUE | 31 | diff still applies; route through the merge train |
| `heads/agent/dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-proofs` | `fc03a2baf7` | RECOVERABLE_VALUE | 4 | diff still applies; route through the merge train |
| `heads/agent/dropbox-hisanta-mastery-engine-grandma-rail-family-slice-2` | `7065f5caf9` | RECOVERABLE_VALUE | 25 | diff still applies; route through the merge train |
| `heads/agent/dropbox-hisanta-mastery-engine-grandma-rail-family-slice-2-clean-129448` | `358297faa1` | RECOVERABLE_VALUE | 11 | diff still applies; route through the merge train |
| `heads/agent/dropbox-hisanta-mastery-engine-grandma-rail-family-slice-3` | `d8497ed3ad` | RECOVERABLE_VALUE | 22 | diff still applies; route through the merge train |
| `heads/agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-batch-fusion-unpause` | `886220ad67` | RECOVERABLE_VALUE | 2 | diff still applies; route through the merge train |
| `heads/agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-billing-guard-scope` | `b06738c9ec` | RECOVERABLE_VALUE | 2 | diff still applies; route through the merge train |
| `heads/agent/dropbox-operator-gate-amendment-auto-ship-authoriz-slice-2` | `60d1a6c325` | RECOVERABLE_VALUE | 28 | diff still applies; route through the merge train |
| `heads/agent/dropbox-pareto-life-goal-autonomy-stack-p4-household-legal-doc-updater-notificat` | `e894c5d775` | RECOVERABLE_VALUE | 23 | diff still applies; route through the merge train |
| `heads/agent/dropbox-pareto-life-goal-autonomy-stack-p5-intergenerational-mesh` | `e8e41f86aa` | CONFLICTED_NEEDS_FOCUSED_TASK | 532 | diff no longer applies; queue a focused follow-up instead of forcing an overwrite |
| `heads/agent/dropbox-pareto-life-goal-autonomy-stack-p6-earnings-only-interface` | `8ae5112bef` | CONFLICTED_NEEDS_FOCUSED_TASK | 447 | diff no longer applies; queue a focused follow-up instead of forcing an overwrite |
| `heads/agent/dropbox-portfolio-doctrine-shared-services-x-items-slice-1` | `973a780feb` | RECOVERABLE_VALUE | 5 | diff still applies; route through the merge train |
| `heads/agent/dropbox-prompt-merged-diff-memory-system-task-spec-group-18` | `8ae5112bef` | CONFLICTED_NEEDS_FOCUSED_TASK | 447 | diff no longer applies; queue a focused follow-up instead of forcing an overwrite |
| `heads/agent/dropbox-prompt-merged-diff-memory-system-task-spec-group-19-wire-merge-detection` | `b926240389` | RECOVERABLE_VALUE | 2 | diff still applies; route through the merge train |
| `heads/agent/dropbox-prompt-merged-diff-memory-system-task-spec-slice-2` | `0a94e7c1b9` | RECOVERABLE_VALUE | 3 | diff still applies; route through the merge train |
| `heads/agent/dropbox-wave-c-compounding-codegen-platform-spine--slice-2` | `59e9731b20` | RECOVERABLE_VALUE | 4 | diff still applies; route through the merge train |
| `heads/agent/dropbox-wave-c-compounding-codegen-platform-spine--slice-4` | `b6fceade87` | RECOVERABLE_VALUE | 3 | diff still applies; route through the merge train |
| `heads/agent/durable-development-session-event-and-artifact-store` | `17a58007c7` | RECOVERABLE_VALUE | 3 | diff still applies; route through the merge train |
| `heads/agent/escalate-p1-queue-clearance-no-improvement-20260810-nk73` | `8ae5112bef` | CONFLICTED_NEEDS_FOCUSED_TASK | 447 | diff no longer applies; queue a focused follow-up instead of forcing an overwrite |
| `heads/agent/factory-unblock-improve-immediate-auto-merge-on-te-slice-4-fix-compilation-types` | `5b7b428573` | RECOVERABLE_VALUE | 29 | diff still applies; route through the merge train |
| `heads/agent/improve-compliance-scheduling-observability` | `ec3696ee3a` | RECOVERABLE_VALUE | 6 | diff still applies; route through the merge train |
| `heads/agent/improve-immediate-auto-merge-on-test-pass-low-r-slice-3-implement-test-completio` | `6b3fd6b909` | RECOVERABLE_VALUE | 2 | diff still applies; route through the merge train |
| `heads/agent/improve-implement-real-time-monitoring-and-alert-slice-3-test-and-commit` | `4708d7b379` | RECOVERABLE_VALUE | 2 | diff still applies; route through the merge train |
| `heads/agent/improve-implement-real-time-sync-between-web-and-slice-2-integrate-real-time-syn` | `58a0f3bff0` | CONFLICTED_NEEDS_FOCUSED_TASK | 416 | diff no longer applies; queue a focused follow-up instead of forcing an overwrite |
| `heads/agent/improve-missing-branch-auto-creator-slice-3-adapt-auto-branch-patch-clean-607415` | `6ad04040c3` | CONFLICTED_NEEDS_FOCUSED_TASK | 447 | diff no longer applies; queue a focused follow-up instead of forcing an overwrite |
| `heads/agent/improve-missing-branch-auto-creator-slice-3-finalize-build-and-config` | `da70b5b058` | CONFLICTED_NEEDS_FOCUSED_TASK | 11 | diff no longer applies; queue a focused follow-up instead of forcing an overwrite |
| `heads/agent/improve-missing-branch-auto-creator-slice-3-locate-decomposition-event-handler-a-clean-152441` | `dc65c5428c` | RECOVERABLE_VALUE | 4 | diff still applies; route through the merge train |
| `heads/agent/improve-queue-prevent-live-runner-merge-conflicts-slice-1` | `213d008c0b` | RECOVERABLE_VALUE | 1 | diff still applies; route through the merge train |
| `heads/agent/improve-streamline-configuration-management-with-slice-2-implement-restful-api-l` | `dcd0b5a334` | RECOVERABLE_VALUE | 2 | diff still applies; route through the merge train |
| `heads/agent/improve-streamline-configuration-management-with-slice-2-integrate-restful-api-l` | `0a4b780848` | RECOVERABLE_VALUE | 4 | diff still applies; route through the merge train |
| `heads/agent/improve-upgrade-to-a-high-performance-database-slice-3-integrate-new-module` | `7bd1aa17c4` | RECOVERABLE_VALUE | 4 | diff still applies; route through the merge train |
| `heads/agent/improve-value-aware-test-routing-early-exit-r-slice-3-add-early-exit-for-low-ev` | `82ae015e7c` | RECOVERABLE_VALUE | 2 | diff still applies; route through the merge train |
| `heads/agent/improve-value-aware-test-routing-early-exit-r-slice-3-fix-broken-tests` | `5197a9b339` | RECOVERABLE_VALUE | 4 | diff still applies; route through the merge train |
| `heads/agent/improve-value-aware-test-routing-early-exit-r-slice-3-fix-broken-tests-clean-151469` | `a9e98fc3c7` | RECOVERABLE_VALUE | 3 | diff still applies; route through the merge train |
| `heads/agent/log-p1-queue-clearance-20260813-t4mq` | `8ae5112bef` | CONFLICTED_NEEDS_FOCUSED_TASK | 447 | diff no longer applies; queue a focused follow-up instead of forcing an overwrite |
| `heads/agent/oc-autoclear-policy` | `300e7e1bde` | RECOVERABLE_VALUE | 2 | diff still applies; route through the merge train |
| `heads/agent/orch-config-consumption` | `b543f49a7c` | RECOVERABLE_VALUE | 2 | diff still applies; route through the merge train |
| `heads/agent/orch-cross-project-depends` | `54b96da161` | RECOVERABLE_VALUE | 5 | diff still applies; route through the merge train |
| `heads/agent/reconcile-conflict-rb` | `9c6d8db815` | RECOVERABLE_VALUE | 1 | diff still applies; route through the merge train |
| `heads/agent/reconcile-conflict-rb-slice-1` | `eb8c927eef` | RECOVERABLE_VALUE | 3 | diff still applies; route through the merge train |
| `heads/agent/recover-missing-branch-dropbox-v4-global-pass-remediations-cross-app-coor-slice-1` | `76fa146e1c` | RECOVERABLE_VALUE | 3 | diff still applies; route through the merge train |
| `heads/agent/recover-stranded-agent-branches-cowork-20260806-slice-2` | `523b86ac74` | RECOVERABLE_VALUE | 5 | diff still applies; route through the merge train |
| `heads/agent/release-on-capacity-not-clock-cowork-20260806` | `870ca7d956` | RECOVERABLE_VALUE | 3 | diff still applies; route through the merge train |
| `heads/agent/relfix-beethoven-299c6b3c3bc6-recovered` | `3dec96c02d` | RECOVERABLE_VALUE | 13 | diff still applies; route through the merge train |
| `heads/agent/relfix-local-lora-distill-add-test-check-add-focused-acceptance-test` | `4eec27f592` | RECOVERABLE_VALUE | 2 | diff still applies; route through the merge train |
| `heads/agent/relfix-vercel-checks-cache-fix-runner-emit-task-log` | `fc528129f6` | RECOVERABLE_VALUE | 1 | diff still applies; route through the merge train |
| `heads/agent/remediate-dropbox-beethoven-audit-addendum-two-session-recon-slice-5-extract-pat` | `1dc1ff02e6` | RECOVERABLE_VALUE | 3 | diff still applies; route through the merge train |
| `heads/agent/remediate-dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-p` | `046e757a84` | RECOVERABLE_VALUE | 3 | diff still applies; route through the merge train |
| `heads/agent/remediate-dropbox-mission-legal-radar-v2-supersedes-the-2026-07-10-prompt-lega-m` | `8ae5112bef` | CONFLICTED_NEEDS_FOCUSED_TASK | 447 | diff no longer applies; queue a focused follow-up instead of forcing an overwrite |
| `heads/agent/remediate-improve-immediate-auto-merge-on-test-pass-low-r-slice-3-locate-existin` | `8ae5112bef` | CONFLICTED_NEEDS_FOCUSED_TASK | 447 | diff no longer applies; queue a focused follow-up instead of forcing an overwrite |
| `heads/agent/remediate-improve-implement-real-time-sync-between-web-and-slice-2-implement-rea` | `8ae5112bef` | CONFLICTED_NEEDS_FOCUSED_TASK | 447 | diff no longer applies; queue a focused follow-up instead of forcing an overwrite |
| `heads/agent/remediate-improve-streamline-merge-workflow-with-ai-based-slice-3-update-documen` | `3a2c567347` | CONFLICTED_NEEDS_FOCUSED_TASK | 532 | diff no longer applies; queue a focused follow-up instead of forcing an overwrite |
| `heads/agent/remediate-improve-value-aware-test-routing-early-exit-r-slice-3-adapt-merged-pat` | `8ae5112bef` | CONFLICTED_NEEDS_FOCUSED_TASK | 447 | diff no longer applies; queue a focused follow-up instead of forcing an overwrite |
| `heads/agent/repository-integration-and-release-owner-leases` | `96a3330126` | RECOVERABLE_VALUE | 5 | diff still applies; route through the merge train |
| `heads/agent/rework-secret-cade-adversary-tournaments-4eab17a` | `4c8d1ed0ab` | RECOVERABLE_VALUE | 2 | diff still applies; route through the merge train |
| `heads/agent/rework-secret-cade-counter-bandit-causal-5186a97` | `9021e27993` | RECOVERABLE_VALUE | 2 | diff still applies; route through the merge train |
| `heads/agent/rework-secret-fix-prompt-delivery-bug-f874164` | `4549352103` | RECOVERABLE_VALUE | 2 | diff still applies; route through the merge train |
| `heads/agent/runner-backed-development-session-broker` | `52a4b29259` | RECOVERABLE_VALUE | 1 | diff still applies; route through the merge train |
| `heads/agent/runner-backed-development-session-broker-slice-1` | `7f3e3d11ff` | RECOVERABLE_VALUE | 2 | diff still applies; route through the merge train |
| `heads/agent/runner-backed-development-session-broker-slice-2` | `f23afe19a3` | RECOVERABLE_VALUE | 3 | diff still applies; route through the merge train |
| `heads/agent/v15-03-spike-attention-budget-slice-1` | `36504dc5e2` | RECOVERABLE_VALUE | 2 | diff still applies; route through the merge train |
| `heads/agent/v15-03-spike-attention-budget-slice-2` | `daed59f71e` | RECOVERABLE_VALUE | 3 | diff still applies; route through the merge train |
| `heads/agent/wedged-governor` | `2b0e14752b` | RECOVERABLE_VALUE | 2 | diff still applies; route through the merge train |
| `heads/agent/wedged-quarantine` | `3b04e7f90e` | RECOVERABLE_VALUE | 2 | diff still applies; route through the merge train |
| `heads/agent/wedged-worktreegc` | `8082492b32` | RECOVERABLE_VALUE | 2 | diff still applies; route through the merge train |
| `heads/backlog-batch-illuminati-1d1b027` | `0abf5b6d4c` | RECOVERABLE_VALUE | 5 | diff still applies; route through the merge train |
| `heads/chatgpt/chatgpt-local-queue-bridge-20260811-08111602` | `cab66e31b3` | RECOVERABLE_VALUE | 12 | diff still applies; route through the merge train |
| `heads/chatgpt/operator-output-truth-session-fabric-20260812-08120203` | `8e22697a6e` | RECOVERABLE_VALUE | 18 | diff still applies; route through the merge train |
| `heads/hotfix/stash-rescue-1785390774-5f879035` | `5f87903566` | RECOVERABLE_VALUE | 6 | diff still applies; route through the merge train |
| `heads/hotfix/stash-rescue-1785390775-782d3cc6` | `782d3cc611` | RECOVERABLE_VALUE | 7 | diff still applies; route through the merge train |
| `heads/hotfix/stash-rescue-1785390775-a234ce54` | `a234ce548c` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | diff no longer applies; queue a focused follow-up instead of forcing an overwrite |
| `heads/hotfix/stash-rescue-1785390775-ac821d4f` | `ac821d4f56` | RECOVERABLE_VALUE | 9 | diff still applies; route through the merge train |
| `heads/hotfix/stash-rescue-1785390775-c7c04c0c` | `c7c04c0cf9` | RECOVERABLE_VALUE | 3 | diff still applies; route through the merge train |
| `heads/hotfix/stash-rescue-1785390777-3cf2968d` | `3cf2968db1` | RECOVERABLE_VALUE | 113 | diff still applies; route through the merge train |
| `heads/hotfix/stash-rescue-1785390777-47bd6566` | `47bd656616` | RECOVERABLE_VALUE | 2 | diff still applies; route through the merge train |
| `heads/hotfix/stash-rescue-1785390777-49c1ed3c` | `49c1ed3c8e` | CONFLICTED_NEEDS_FOCUSED_TASK | 12 | diff no longer applies; queue a focused follow-up instead of forcing an overwrite |
| `heads/hotfix/stash-rescue-1785390777-dca295aa` | `dca295aa00` | CONFLICTED_NEEDS_FOCUSED_TASK | 1021 | diff no longer applies; queue a focused follow-up instead of forcing an overwrite |
| `heads/hotfix/stash-rescue-1785390777-e0d68470` | `e0d684705a` | CONFLICTED_NEEDS_FOCUSED_TASK | 8 | diff no longer applies; queue a focused follow-up instead of forcing an overwrite |
| `heads/hotfix/stash-rescue-1785443042-cba52338` | `cba52338fc` | RECOVERABLE_VALUE | 2 | diff still applies; route through the merge train |
| `heads/hotfix/stash-rescue-1785473643-d220d0a9` | `d220d0a989` | RECOVERABLE_VALUE | 3 | diff still applies; route through the merge train |
| `heads/hotfix/stash-rescue-1785526243-d39b39d6` | `d39b39d620` | RECOVERABLE_VALUE | 1 | diff still applies; route through the merge train |
| `heads/hotfix/stash-rescue-lease-night-5f879035` | `5f87903566` | RECOVERABLE_VALUE | 6 | diff still applies; route through the merge train |

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
