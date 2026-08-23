# Recovery ledger — beethoven

- audit fingerprint: `a7e24596154fadb13a6f78e66328e6b29c178f30384146310d33894483062899`
- base: `origin/master`
- evidence items classified: **710**
- UNKNOWN remaining: **0**

Every rescue ref was treated as read-only. No ref, stash or worktree
was deleted, reset, cleaned, popped or moved by this reconciliation.

## Classification summary

| classification | count |
| --- | ---: |
| RECOVERABLE_VALUE | 56 |
| CONFLICTED_NEEDS_FOCUSED_TASK | 97 |
| ACTIVE_IN_ANOTHER_TASK | 47 |
| SUPERSEDED_BY_NEWER | 229 |
| ALREADY_PRESENT | 281 |

## Items needing follow-up

| ref | sha | class | files | disposition |
| --- | --- | --- | ---: | --- |
| `orch-rescue/20260803T000726-relfix-racefeed-07060650-slice-4` | `9c023d06b7` | CONFLICTED_NEEDS_FOCUSED_TASK | 4 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260803T000752-relfix-racefeed-07060650-slice-4` | `5152ab956f` | CONFLICTED_NEEDS_FOCUSED_TASK | 4 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260803T001521-relfix-racefeed-07060650-slice-4-ad00f1c9` | `ad00f1c964` | CONFLICTED_NEEDS_FOCUSED_TASK | 4 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260805T145454-deployfix-beethoven-07190338-fix-and-verify-vercel-production-build-423c51ca` | `423c51ca9a` | RECOVERABLE_VALUE | 1 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260805T191227-cc-mutual-default-fund-1d7e8d9a` | `1d7e8d9a0f` | CONFLICTED_NEEDS_FOCUSED_TASK | 1993 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260805T191228-cc-solvency-passport-6138fffd` | `6138fffd67` | CONFLICTED_NEEDS_FOCUSED_TASK | 355 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260806T100003-improve-missing-branch-auto-creator-slice-3-locate-decomposition-event-handler-a-bedc007c` | `bedc007cc0` | RECOVERABLE_VALUE | 1 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260806T100004-improve-value-aware-test-routing-early-exit-r-slice-3-adapt-merged-patterns-65464532` | `6546453246` | RECOVERABLE_VALUE | 1 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260806T131026-improve-value-aware-test-routing-early-exit-r-slice-3-adapt-merged-patterns-d09561bf` | `d09561bff0` | CONFLICTED_NEEDS_FOCUSED_TASK | 1289 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260806T131034-5bee398fbf584c3252b3-57b674c5` | `57b674c557` | CONFLICTED_NEEDS_FOCUSED_TASK | 2583 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260806T161111-relfix-release-hold-deadlock-cowork-20260806-e9050616` | `e9050616be` | CONFLICTED_NEEDS_FOCUSED_TASK | 3 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260806T172735-dropbox-operator-gate-amendment-auto-ship-authoriz-slice-2-9225b0f5` | `9225b0f507` | CONFLICTED_NEEDS_FOCUSED_TASK | 3 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260806T201809-improve-value-aware-test-routing-early-exit-r-slice-3-fix-broken-tests-ba304347` | `ba3043475f` | CONFLICTED_NEEDS_FOCUSED_TASK | 2 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260806T202615-improve-value-aware-test-routing-early-exit-r-slice-3-fix-broken-tests-63cf225e` | `63cf225ebc` | CONFLICTED_NEEDS_FOCUSED_TASK | 3 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260806T215726-unbounded-scan-window-class-audit-cowork-20260806-512f19be` | `512f19be82` | CONFLICTED_NEEDS_FOCUSED_TASK | 5 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260806T221512-fix-compilation-types-4fb310c6` | `4fb310c6e6` | CONFLICTED_NEEDS_FOCUSED_TASK | 14 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260806T224241-improve-upgrade-to-a-high-performance-database-slice-3-integrate-new-module-aa3c1231` | `aa3c123138` | RECOVERABLE_VALUE | 4 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260806T224945-relfix-racefeed-07060650-fix-typescript-and-build--slice-4-fix-missing-branch-7d9bd79d` | `7d9bd79d37` | CONFLICTED_NEEDS_FOCUSED_TASK | 2189 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260807T015247-dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-p4-releasetrain-vercel-9c79f8f6` | `9c79f8f60c` | CONFLICTED_NEEDS_FOCUSED_TASK | 1439 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260807T125256-orchestrator-visibility-remediation-15d8c552` | `15d8c55228` | CONFLICTED_NEEDS_FOCUSED_TASK | 15 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260807T130647-orchestrator-visibility-remediation-a05140c3` | `a05140c32f` | CONFLICTED_NEEDS_FOCUSED_TASK | 16 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260807T173615-claude-orchestrator-12001806` | `12001806df` | RECOVERABLE_VALUE | 2 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260807T220546-improve-automate-branch-management-slice-3-310c54b3` | `310c54b335` | CONFLICTED_NEEDS_FOCUSED_TASK | 1644 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260808T040916-improve-immediate-auto-merge-on-test-pass-low-r-slice-3-implement-test-completio-7bf524c4` | `7bf524c475` | CONFLICTED_NEEDS_FOCUSED_TASK | 256 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260808T184515-cade-mirror-negotiation-5d33743e` | `5d33743e80` | CONFLICTED_NEEDS_FOCUSED_TASK | 1786 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260808T184519-canary-claude-27-slice-3-update-tests-checks-analyze-patch-behavior-analyze-patc-a4a7ec82` | `a4a7ec82a3` | CONFLICTED_NEEDS_FOCUSED_TASK | 851 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260811T152527-orchestrator-session-fabric-current-364b3d7a` | `364b3d7a04` | CONFLICTED_NEEDS_FOCUSED_TASK | 15 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260813T034449-orchestrator-session-fabric-current-7ba40cac` | `7ba40cacae` | CONFLICTED_NEEDS_FOCUSED_TASK | 18 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260813T045320-reconcile-beethoven-55acd60c-ed040682` | `ed0406825f` | CONFLICTED_NEEDS_FOCUSED_TASK | 18 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260813T080048-chatgpt-local-reconcile-beethoven-ac93979d6c7a-1da71dac` | `1da71dac94` | CONFLICTED_NEEDS_FOCUSED_TASK | 2 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260813T083737-chatgpt-local-reconcile-beethoven-383306e1301e-633e1610` | `633e1610b3` | CONFLICTED_NEEDS_FOCUSED_TASK | 4 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260813T091206-chatgpt-local-reconcile-beethoven-3b50d1e569de-d0ecb81c` | `d0ecb81c68` | CONFLICTED_NEEDS_FOCUSED_TASK | 2 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260813T102021-chatgpt-local-reconcile-beethoven-5e30d0e05126-4ecfa8aa` | `4ecfa8aa75` | CONFLICTED_NEEDS_FOCUSED_TASK | 2 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260813T102021-chatgpt-local-reconcile-beethoven-84fc83c513d9-4ecfa8aa` | `4ecfa8aa75` | CONFLICTED_NEEDS_FOCUSED_TASK | 2 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260813T201101-pinned-express-814604f7` | `814604f710` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260813T201603-pinned-express-dcf328aa` | `dcf328aaa8` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260813T202224-pinned-express-739d0d24` | `739d0d249f` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260813T205213-dropbox-beethoven-audit-addendum-two-session-reconciliation-read-wit-group-5-3213f4fa` | `3213f4fa8f` | CONFLICTED_NEEDS_FOCUSED_TASK | 2 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260813T213903-dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-3-speed-triage-routing-accelerators-p0-28c0982f` | `28c0982f84` | RECOVERABLE_VALUE | 1 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260813T233826-c27-minimal-680be7c7` | `680be7c71c` | RECOVERABLE_VALUE | 1 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260813T234327-c27-minimal-649efcae` | `649efcae3b` | RECOVERABLE_VALUE | 1 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260814T001818-canary-claude-27-slice-1-run-checks-90a1e704` | `90a1e70413` | CONFLICTED_NEEDS_FOCUSED_TASK | 8 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260814T043640-backlog-batch-beethoven-a86bb21-recover-pinned-exp-slice-1-26b72d0b` | `26b72d0b1a` | RECOVERABLE_VALUE | 2 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260814T044159-backlog-batch-beethoven-a86bb21-recover-pinned-exp-slice-1-50dd28e3` | `50dd28e386` | CONFLICTED_NEEDS_FOCUSED_TASK | 3 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260814T045028-dropbox-recover-lease-night-g1-95167518` | `951675184a` | RECOVERABLE_VALUE | 1 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260814T045639-backlog-batch-beethoven-d3151d8-d2055a73` | `d2055a738b` | RECOVERABLE_VALUE | 1 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260814T050204-backlog-batch-beethoven-d3151d8-87d761c1` | `87d761c1ab` | RECOVERABLE_VALUE | 1 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260815T155037-backlog-batch-beethoven-a86bb21-recover-pinned-exp-slice-1-3568709e` | `3568709ebd` | RECOVERABLE_VALUE | 2 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260815T155824-backlog-batch-beethoven-a86bb21-recover-pinned-exp-slice-1-519f71f7` | `519f71f716` | RECOVERABLE_VALUE | 3 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260815T160343-backlog-batch-beethoven-a86bb21-recover-pinned-exp-slice-1-6383c3a4` | `6383c3a493` | RECOVERABLE_VALUE | 3 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260815T160936-backlog-batch-beethoven-a86bb21-recover-pinned-exp-slice-1-fb89ac45` | `fb89ac4547` | RECOVERABLE_VALUE | 4 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260815T171020-claude-orchestrator-03d90b53` | `03d90b5302` | RECOVERABLE_VALUE | 2 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260815T180824-canary-gemini-25-canary-gemini-25-setup-install-dependencies-7171a247` | `7171a24710` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260815T181331-canary-gemini-25-canary-gemini-25-setup-install-dependencies-97ff52d0` | `97ff52d03e` | CONFLICTED_NEEDS_FOCUSED_TASK | 3 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260815T181909-canary-gemini-25-canary-gemini-25-setup-install-dependencies-ea35b8b0` | `ea35b8b0d4` | CONFLICTED_NEEDS_FOCUSED_TASK | 4 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260815T185730-claude-orchestrator-f43954f3` | `f43954f345` | RECOVERABLE_VALUE | 2 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260815T200110-canary-gemini-25-canary-gemini-25-setup-install-dependencies-85fe983d` | `85fe983d3d` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260815T202759-canary-gemini-25-canary-gemini-25-setup-install-dependencies-c74d8a5f` | `c74d8a5f59` | RECOVERABLE_VALUE | 4 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260815T230609-chatgpt-local-reconcile-beethoven-fa219072749e-06d3b538` | `06d3b5384d` | RECOVERABLE_VALUE | 1 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260815T231152-chatgpt-local-reconcile-beethoven-fa219072749e-0efcd03c` | `0efcd03cb0` | RECOVERABLE_VALUE | 1 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260815T233403-claude-orchestrator-b8ad611d` | `b8ad611d8c` | RECOVERABLE_VALUE | 2 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260816T230458-safe-edit-e6b8d2b8` | `e6b8d2b8e0` | CONFLICTED_NEEDS_FOCUSED_TASK | 685 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260816T231100-safe-edit-768fbf8d` | `768fbf8d3d` | CONFLICTED_NEEDS_FOCUSED_TASK | 5 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260817T000523-safe-edit-42706744` | `427067448d` | RECOVERABLE_VALUE | 1 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260817T002648-claude-orchestrator-7422235e` | `7422235e82` | RECOVERABLE_VALUE | 8 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260817T005618-claude-orchestrator-ee6371c7` | `ee6371c727` | RECOVERABLE_VALUE | 1 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260817T010230-claude-orchestrator-a10db3f9` | `a10db3f93b` | RECOVERABLE_VALUE | 2 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260817T010232-chatgpt-local-reconcile-beethoven-55acd60c79b1-3214adae` | `3214adae9d` | RECOVERABLE_VALUE | 1 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260817T012755-claude-orchestrator-b8b842a0` | `b8b842a03f` | RECOVERABLE_VALUE | 3 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260817T014951-claude-orchestrator-8414e002` | `8414e0021e` | RECOVERABLE_VALUE | 3 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260817T015601-chatgpt-local-reconcile-beethoven-8d0702cbd5aa-fb7d0c1d` | `fb7d0c1daa` | RECOVERABLE_VALUE | 2 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260817T020154-chatgpt-local-reconcile-beethoven-671c267eedf3-74b8aed7` | `74b8aed7d5` | RECOVERABLE_VALUE | 2 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260817T020832-chatgpt-local-reconcile-beethoven-7b6f925e1e7a-2e4c82d4` | `2e4c82d438` | RECOVERABLE_VALUE | 2 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260817T020836-chatgpt-local-reconcile-beethoven-ca93a1b7be55-e6107650` | `e61076505e` | RECOVERABLE_VALUE | 2 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260817T035301-chatgpt-local-reconcile-beethoven-85d2de799d5d-6c8ea700` | `6c8ea7007d` | RECOVERABLE_VALUE | 2 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260817T035848-release-on-capacity-not-clock-cowork-20260806-3805ac77` | `3805ac77d6` | RECOVERABLE_VALUE | 1 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260817T042205-claude-orchestrator-7be6642b` | `7be6642b48` | RECOVERABLE_VALUE | 6 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260817T043934-chatgpt-local-reconcile-beethoven-8d0702cbd5aa-99b90f7e` | `99b90f7ee3` | CONFLICTED_NEEDS_FOCUSED_TASK | 69 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260817T044527-chatgpt-local-reconcile-beethoven-8d0702cbd5aa-bf68cd93` | `bf68cd9329` | CONFLICTED_NEEDS_FOCUSED_TASK | 68 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260817T055034-immune-p0-3fcda7b3` | `3fcda7b303` | RECOVERABLE_VALUE | 2 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260817T055035-p4-household-5fdeb7e6` | `5fdeb7e679` | RECOVERABLE_VALUE | 2 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260817T060324-claude-orchestrator-cf499098` | `cf49909832` | RECOVERABLE_VALUE | 5 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260817T112512-claude-orchestrator-0d04c7ce` | `0d04c7cecb` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260817T113054-claude-orchestrator-e92444f3` | `e92444f3df` | CONFLICTED_NEEDS_FOCUSED_TASK | 4 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260817T113726-claude-orchestrator-d7514abd` | `d7514abdb0` | CONFLICTED_NEEDS_FOCUSED_TASK | 3 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260817T115556-claude-orchestrator-8c0cc172` | `8c0cc172e5` | CONFLICTED_NEEDS_FOCUSED_TASK | 4 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260817T123448-claude-orchestrator-2fc327e2` | `2fc327e2de` | CONFLICTED_NEEDS_FOCUSED_TASK | 18 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260817T131917-claude-orchestrator-652f765e` | `652f765e05` | CONFLICTED_NEEDS_FOCUSED_TASK | 2 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260817T133255-claude-orchestrator-7c7997db` | `7c7997db0c` | CONFLICTED_NEEDS_FOCUSED_TASK | 2 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260817T135423-claude-orchestrator-099fca82` | `099fca82ce` | CONFLICTED_NEEDS_FOCUSED_TASK | 5 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260817T144019-claude-orchestrator-4491388f` | `4491388ff5` | CONFLICTED_NEEDS_FOCUSED_TASK | 6 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260817T163844-claude-orchestrator-253a58a2` | `253a58a2fd` | CONFLICTED_NEEDS_FOCUSED_TASK | 6 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260817T165035-claude-orchestrator-3d286316` | `3d286316f2` | CONFLICTED_NEEDS_FOCUSED_TASK | 7 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260817T170154-5bee398fbf584c3252b3-dbb4100a` | `dbb4100a6d` | RECOVERABLE_VALUE | 2 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260817T195309-claude-orchestrator-60a69d29` | `60a69d293c` | CONFLICTED_NEEDS_FOCUSED_TASK | 7 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260817T195652-claude-orchestrator-375cf3e2` | `375cf3e207` | CONFLICTED_NEEDS_FOCUSED_TASK | 7 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260817T203201-claude-orchestrator-973bfa94` | `973bfa949e` | CONFLICTED_NEEDS_FOCUSED_TASK | 8 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260817T204846-claude-orchestrator-0d560ffc` | `0d560ffcd6` | CONFLICTED_NEEDS_FOCUSED_TASK | 7 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260817T212406-claude-orchestrator-482a8b20` | `482a8b2002` | CONFLICTED_NEEDS_FOCUSED_TASK | 8 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260817T213202-claude-orchestrator-76839db4` | `76839db4a6` | CONFLICTED_NEEDS_FOCUSED_TASK | 8 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260817T221401-claude-orchestrator-730e985a` | `730e985a72` | CONFLICTED_NEEDS_FOCUSED_TASK | 6 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260817T222536-claude-orchestrator-af391283` | `af391283a0` | CONFLICTED_NEEDS_FOCUSED_TASK | 8 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260817T225402-claude-orchestrator-134b6d24` | `134b6d243a` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260817T230447-claude-orchestrator-8f5c2842` | `8f5c2842f0` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260817T233242-claude-orchestrator-fc01933c` | `fc01933c47` | CONFLICTED_NEEDS_FOCUSED_TASK | 10 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260817T233903-claude-orchestrator-d5c936db` | `d5c936db30` | CONFLICTED_NEEDS_FOCUSED_TASK | 13 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260818T000832-claude-orchestrator-5eeba5f9` | `5eeba5f9c0` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260818T001410-claude-orchestrator-f0f81912` | `f0f81912cb` | RECOVERABLE_VALUE | 1 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260818T035033-claude-orchestrator-5728bd08` | `5728bd0884` | CONFLICTED_NEEDS_FOCUSED_TASK | 5 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260818T035837-claude-orchestrator-587bc54d` | `587bc54ddf` | CONFLICTED_NEEDS_FOCUSED_TASK | 6 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260818T040454-claude-orchestrator-5698db33` | `5698db33ce` | CONFLICTED_NEEDS_FOCUSED_TASK | 7 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260818T054245-claude-orchestrator-90114ecd` | `90114ecd17` | CONFLICTED_NEEDS_FOCUSED_TASK | 616 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260818T054802-claude-orchestrator-403223c6` | `403223c6a7` | CONFLICTED_NEEDS_FOCUSED_TASK | 617 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260818T055317-claude-orchestrator-5aa0c675` | `5aa0c675bd` | CONFLICTED_NEEDS_FOCUSED_TASK | 136 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260818T060258-claude-orchestrator-f8e534a2` | `f8e534a239` | CONFLICTED_NEEDS_FOCUSED_TASK | 137 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260818T063115-claude-orchestrator-73a065c3` | `73a065c390` | CONFLICTED_NEEDS_FOCUSED_TASK | 137 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260818T075120-claude-orchestrator-33b86167` | `33b8616759` | CONFLICTED_NEEDS_FOCUSED_TASK | 137 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260818T103648-contracts-smarter-add95f9a` | `add95f9aca` | CONFLICTED_NEEDS_FOCUSED_TASK | 1573 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260818T122151-regen-improve-enhance-automated-testing-and-integratio-slice-5-4247669a` | `4247669a82` | CONFLICTED_NEEDS_FOCUSED_TASK | 1168 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260818T122208-regen-improve-enhance-testing-framework-slice-5-be5ab02f` | `be5ab02f71` | CONFLICTED_NEEDS_FOCUSED_TASK | 200 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260818T122214-regen-recover-missing-branch-backlog-blitz-context-diet-verify-2d556ab2` | `2d556ab274` | CONFLICTED_NEEDS_FOCUSED_TASK | 1773 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260818T122220-smarter-5-95-600d016e` | `600d016e9e` | CONFLICTED_NEEDS_FOCUSED_TASK | 745 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260818T122238-stub-recover-missing-branch-backlog-blitz-context-diet-verify-5bd230e2` | `5bd230e20d` | CONFLICTED_NEEDS_FOCUSED_TASK | 1926 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260818T125128-rework-secret-a2a-endpoint-0743615-a53b0c69` | `a53b0c69bb` | CONFLICTED_NEEDS_FOCUSED_TASK | 1141 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260818T131320-improve-streamline-merge-workflow-with-ai-based-slice-4-cceb0701` | `cceb070137` | CONFLICTED_NEEDS_FOCUSED_TASK | 2371 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260818T203212-session-proof-of-work-01b79c13` | `01b79c13ad` | CONFLICTED_NEEDS_FOCUSED_TASK | 25 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260818T203824-claude-orchestrator-0869dcec` | `0869dcec64` | RECOVERABLE_VALUE | 3 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260818T204903-claude-orchestrator-5ef4f2f3` | `5ef4f2f3ad` | RECOVERABLE_VALUE | 4 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260818T225528-claude-orchestrator-2f21a5fc` | `2f21a5fce5` | RECOVERABLE_VALUE | 7 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260818T230930-claude-orchestrator-083a3ca3` | `083a3ca39b` | RECOVERABLE_VALUE | 7 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260819T004528-claude-orchestrator-2869c6dd` | `2869c6ddec` | RECOVERABLE_VALUE | 4 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260819T005543-claude-orchestrator-65c7c93b` | `65c7c93bee` | RECOVERABLE_VALUE | 4 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260819T010706-claude-orchestrator-4d1f61cf` | `4d1f61cfc6` | RECOVERABLE_VALUE | 4 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260819T011309-claude-orchestrator-6f0a4bd5` | `6f0a4bd571` | RECOVERABLE_VALUE | 5 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260819T012304-claude-orchestrator-d3bf7c09` | `d3bf7c098b` | RECOVERABLE_VALUE | 6 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260819T013753-reconcile-wt-2b229a51` | `2b229a5150` | CONFLICTED_NEEDS_FOCUSED_TASK | 5 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260819T014337-claude-orchestrator-4c85e621` | `4c85e6215b` | RECOVERABLE_VALUE | 6 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260819T122933-claude-orchestrator-51d01a03` | `51d01a035c` | RECOVERABLE_VALUE | 13 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `heads/agent/dropbox-hisanta-mastery-engine-grandma-rail-family-slice-2-clean-129448` | `358297faa1` | CONFLICTED_NEEDS_FOCUSED_TASK | 11 | range diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `heads/agent/improve-missing-branch-auto-creator-slice-3-locate-decomposition-event-handler-a-clean-152441` | `dc65c5428c` | CONFLICTED_NEEDS_FOCUSED_TASK | 4 | range diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `heads/agent/improve-value-aware-test-routing-early-exit-r-slice-3-fix-broken-tests-clean-151469` | `a9e98fc3c7` | CONFLICTED_NEEDS_FOCUSED_TASK | 3 | range diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `heads/backup-node-precatchup2-20260818` | `ee62af4431` | CONFLICTED_NEEDS_FOCUSED_TASK | 2 | range diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `heads/improve/cost-ledger-fail-soft` | `b0ba3f39e9` | RECOVERABLE_VALUE | 1 | range diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/backlog-batch-beethoven-22ee5bc-convention-conform-slice-2 8309febb` | `1eda33098a` | CONFLICTED_NEEDS_FOCUSED_TASK | 2 | uncommitted tracked diff no longer applies to base; queue a focused follow-up rather than forcing an overwrite |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/backlog-batch-beethoven-22ee5bc-prompt-evolution-bandit-update-claude-interface 67280171` | `76d068867d` | CONFLICTED_NEEDS_FOCUSED_TASK | 2 | uncommitted tracked diff no longer applies to base; queue a focused follow-up rather than forcing an overwrite |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/canary-claude-27-slice-3-adapt-prior-merged-patterns-extract-proven-diffs-extrac 15227eb7` | `ba57d64f0f` | CONFLICTED_NEEDS_FOCUSED_TASK | 2 | uncommitted tracked diff no longer applies to base; queue a focused follow-up rather than forcing an overwrite |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/spine-types-x2` | `987e5280e7` | RECOVERABLE_VALUE | 1 | 1 untracked new file(s) with no tracked counterpart; review and land through an agent branch. Source left untouched. |
| `/Users/kpasch/Documents/Codex/2026-08-06/figu/work/orchestrator-visibility-remediation` | `fbb735b3cf` | CONFLICTED_NEEDS_FOCUSED_TASK | 17 | uncommitted tracked diff no longer applies to base; queue a focused follow-up rather than forcing an overwrite |
| `/Users/kpasch/Documents/Codex/2026-08-07/cons/work/orchestrator-session-fabric-current` | `59de85f238` | CONFLICTED_NEEDS_FOCUSED_TASK | 18 | uncommitted tracked diff no longer applies to base; queue a focused follow-up rather than forcing an overwrite |
| `/Users/kpasch/Documents/chatgpt-dropbox/_applied/20260817-192242--apparently--absorb-otc-payoff-slice1-20260817.patch` | `0d42e139cd` | RECOVERABLE_VALUE | 4 | bridge marked this applied, but the patch still applies to origin/master -- the change never reached the default branch. Recover through an agent branch. |
| `/Users/kpasch/Documents/chatgpt-dropbox/_applied/20260817-201758--apparently--absorb-otc-payoff-slice1-v2-20260818.patch` | `e1f71dc951` | RECOVERABLE_VALUE | 8 | bridge marked this applied, but the patch still applies to origin/master -- the change never reached the default branch. Recover through an agent branch. |
| `/Users/kpasch/Documents/chatgpt-dropbox/_failed/20260807-085521--smarter--apparently-framework-merge.patch` | `6b8f95f50a` | CONFLICTED_NEEDS_FOCUSED_TASK | 68 | failed bridge artifact whose patch no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `/Users/kpasch/Documents/chatgpt-dropbox/_to_delete/local-only-runner-code.diff` | `7e4e3ef259` | CONFLICTED_NEEDS_FOCUSED_TASK | 68 | failed bridge artifact whose patch no longer applies; queue a focused follow-up rather than forcing an overwrite |

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
