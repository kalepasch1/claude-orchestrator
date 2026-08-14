# Recovery ledger — beethoven (rescue refs)

- audit fingerprint: `e9e37e7ea69d`
- base: `origin/master`
- evidence items classified: **408**
- UNKNOWN remaining: **0**

Every rescue ref was treated as read-only. No ref, stash or worktree
was deleted, reset, cleaned, popped or moved by this reconciliation.

## Classification summary

| classification | count |
| --- | ---: |
| RECOVERABLE_VALUE | 22 |
| CONFLICTED_NEEDS_FOCUSED_TASK | 59 |
| ACTIVE_IN_ANOTHER_TASK | 9 |
| SUPERSEDED_BY_NEWER | 252 |
| ALREADY_PRESENT | 66 |

## Items needing follow-up

| ref | sha | class | files | disposition |
| --- | --- | --- | ---: | --- |
| `orch-rescue/20260803T000718-breach-remediation` | `72bc7ddf1f` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260803T000719-cade-mirror-negotiation` | `696872815d` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260803T000720-cc-legacy-margin-removal` | `c3d1aa9ea8` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260803T000721-cc-mutual-default-fund` | `54cb2405c8` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260803T000721-cc-solvency-passport` | `cb458638f9` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260803T000722-convention-conformance-lints` | `7530399a51` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260803T000723-economic-scheduler-revenue` | `c23fdeee47` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260803T000724-ext-streaming-terms` | `93d532b1c5` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260803T000724-hive-enforcement-velocity-index` | `62602aee6f` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260803T000724-merged-diff-memory` | `791ce633ee` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260803T000725-oc-autoclear-policy` | `4202f5b49f` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260803T000725-orch-config-consumption` | `0bee7ff2f1` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260803T000725-pinned-express-lane` | `5f3ed25ef5` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260803T000725-ploeh-s2s-bridge-tomorrow` | `17646f8e58` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260803T000726-prompt-evolution-bandit` | `c724ed3243` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260803T000726-relfix-racefeed-07060650-slice-4` | `9c023d06b7` | RECOVERABLE_VALUE | 4 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260803T000751-breach-remediation` | `1ae53af030` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260803T000751-cade-mirror-negotiation` | `730ac4d5e6` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260803T000751-cc-legacy-margin-removal` | `eb0f0cb53c` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260803T000751-cc-mutual-default-fund` | `ef9819ce08` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260803T000751-cc-solvency-passport` | `f87dd58807` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260803T000751-convention-conformance-lints` | `e493983279` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260803T000751-economic-scheduler-revenue` | `4b70e54e5e` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260803T000752-ext-streaming-terms` | `1a057825f6` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260803T000752-hive-enforcement-velocity-index` | `c9f3f13cb6` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260803T000752-merged-diff-memory` | `6224b1d813` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260803T000752-oc-autoclear-policy` | `925cb1cb72` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260803T000752-orch-config-consumption` | `8e413e3adb` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260803T000752-pinned-express-lane` | `e950039289` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260803T000752-ploeh-s2s-bridge-tomorrow` | `4a4d3ade80` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260803T000752-prompt-evolution-bandit` | `56af7e4488` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260803T000752-relfix-racefeed-07060650-slice-4` | `5152ab956f` | RECOVERABLE_VALUE | 4 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260803T001519-breach-remediation-edd348c6` | `edd348c63f` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260803T001519-cade-mirror-negotiation-d68cf226` | `d68cf22624` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260803T001519-cc-legacy-margin-removal-4567c246` | `4567c24689` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260803T001519-cc-mutual-default-fund-dae1f8a6` | `dae1f8a600` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260803T001519-cc-solvency-passport-68109d8d` | `68109d8de8` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260803T001520-convention-conformance-lints-bc7d6dbe` | `bc7d6dbebc` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260803T001520-economic-scheduler-revenue-56470d9b` | `56470d9b78` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260803T001520-ext-streaming-terms-c6192d95` | `c6192d95db` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260803T001520-hive-enforcement-velocity-index-2a19e4c2` | `2a19e4c2e1` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260803T001520-merged-diff-memory-7035e861` | `7035e861c3` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260803T001520-oc-autoclear-policy-a78462c9` | `a78462c96e` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260803T001520-orch-config-consumption-2e8791a8` | `2e8791a822` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260803T001520-pinned-express-lane-82ebabc3` | `82ebabc33e` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260803T001520-ploeh-s2s-bridge-tomorrow-ff7a7cb5` | `ff7a7cb539` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260803T001521-prompt-evolution-bandit-af40b683` | `af40b683e9` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
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
| `orch-rescue/20260807T001758-low-ev-early-exit-b706cb92` | `b706cb92c4` | RECOVERABLE_VALUE | 1 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260807T003642-backlog-batch-beethoven-ccacb00-fix-failing-tests-identify-failing-tests-3c9337d5` | `3c9337d5c1` | CONFLICTED_NEEDS_FOCUSED_TASK | 129 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
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
| `orch-rescue/20260813T091206-canary-claude-27-slice-3-adapt-prior-merged-patterns-extract-proven-diffs-docume-ed55d2b0` | `ed55d2b0d1` | RECOVERABLE_VALUE | 1 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |

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
