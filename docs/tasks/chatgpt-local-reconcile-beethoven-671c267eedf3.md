# Recovery ledger — beethoven

- audit fingerprint: `671c267eedf3f831e2dca9ef7f81cdf779a194fc5bd534e339e471804ce8f004`
- base: `origin/master`
- evidence items classified: **664**
- UNKNOWN remaining: **0**

Every rescue ref was treated as read-only. No ref, stash or worktree
was deleted, reset, cleaned, popped or moved by this reconciliation.

## Classification summary

| classification | count |
| --- | ---: |
| RECOVERABLE_VALUE | 61 |
| CONFLICTED_NEEDS_FOCUSED_TASK | 56 |
| ACTIVE_IN_ANOTHER_TASK | 3 |
| SUPERSEDED_BY_NEWER | 309 |
| ALREADY_PRESENT | 235 |

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
| `orch-rescue/20260811T152527-orchestrator-session-fabric-current-364b3d7a` | `364b3d7a04` | RECOVERABLE_VALUE | 15 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260813T034449-orchestrator-session-fabric-current-7ba40cac` | `7ba40cacae` | RECOVERABLE_VALUE | 18 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260813T045320-reconcile-beethoven-55acd60c-ed040682` | `ed0406825f` | RECOVERABLE_VALUE | 18 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260813T063106-chatgpt-local-reconcile-beethoven-6c8911116873-36ff050f` | `36ff050f9d` | CONFLICTED_NEEDS_FOCUSED_TASK | 3 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260813T072604-chatgpt-local-reconcile-beethoven-215fba971ab9-e48843cd` | `e48843cde6` | CONFLICTED_NEEDS_FOCUSED_TASK | 2 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260813T072605-chatgpt-local-reconcile-beethoven-4d83819ff744-e48843cd` | `e48843cde6` | CONFLICTED_NEEDS_FOCUSED_TASK | 2 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260813T072605-chatgpt-local-reconcile-beethoven-797668765dad-e48843cd` | `e48843cde6` | CONFLICTED_NEEDS_FOCUSED_TASK | 2 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260813T080048-chatgpt-local-reconcile-beethoven-ac93979d6c7a-1da71dac` | `1da71dac94` | CONFLICTED_NEEDS_FOCUSED_TASK | 2 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260813T081746-chatgpt-local-reconcile-beethoven-e0945946bd0d-45fefc8b` | `45fefc8b78` | CONFLICTED_NEEDS_FOCUSED_TASK | 2 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260813T083737-chatgpt-local-reconcile-beethoven-383306e1301e-633e1610` | `633e1610b3` | CONFLICTED_NEEDS_FOCUSED_TASK | 4 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260813T084725-fix-canonical-enqueue-trigger-regression-20260812-7bf01722` | `7bf017227d` | RECOVERABLE_VALUE | 2 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260813T085137-fix-canonical-enqueue-trigger-regression-20260812-cd80d50c` | `cd80d50c94` | RECOVERABLE_VALUE | 2 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
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
| `orch-rescue/20260815T194812-claude-orchestrator-ca7e84ca` | `ca7e84ca0c` | RECOVERABLE_VALUE | 4 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260815T195439-claude-orchestrator-ebc35563` | `ebc355630f` | RECOVERABLE_VALUE | 1 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260815T200110-canary-gemini-25-canary-gemini-25-setup-install-dependencies-85fe983d` | `85fe983d3d` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260815T201040-dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-batch-fusion-unpause-f728f655` | `f728f6558e` | RECOVERABLE_VALUE | 1 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260815T202759-canary-gemini-25-canary-gemini-25-setup-install-dependencies-c74d8a5f` | `c74d8a5f59` | RECOVERABLE_VALUE | 4 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260815T215740-claude-orchestrator-f935294a` | `f935294ae9` | RECOVERABLE_VALUE | 2 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260815T224825-claude-orchestrator-bf19be4d` | `bf19be4d0c` | RECOVERABLE_VALUE | 1 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260815T230027-claude-orchestrator-f049ff3b` | `f049ff3bbc` | RECOVERABLE_VALUE | 4 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260815T230608-claude-orchestrator-6beec314` | `6beec3143c` | RECOVERABLE_VALUE | 1 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260815T230609-chatgpt-local-reconcile-beethoven-fa219072749e-06d3b538` | `06d3b5384d` | RECOVERABLE_VALUE | 1 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260815T231152-chatgpt-local-reconcile-beethoven-fa219072749e-0efcd03c` | `0efcd03cb0` | RECOVERABLE_VALUE | 1 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260815T233403-claude-orchestrator-b8ad611d` | `b8ad611d8c` | RECOVERABLE_VALUE | 2 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260815T235049-claude-orchestrator-060c1f47` | `060c1f4746` | RECOVERABLE_VALUE | 2 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260816T225433-claude-orchestrator-9ed89d5f` | `9ed89d5fe4` | RECOVERABLE_VALUE | 4 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260816T230458-safe-edit-e6b8d2b8` | `e6b8d2b8e0` | CONFLICTED_NEEDS_FOCUSED_TASK | 685 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260816T231100-safe-edit-768fbf8d` | `768fbf8d3d` | RECOVERABLE_VALUE | 5 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260816T231604-claude-orchestrator-ef07b604` | `ef07b6040b` | RECOVERABLE_VALUE | 7 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260816T234850-claude-orchestrator-2b12f025` | `2b12f02518` | CONFLICTED_NEEDS_FOCUSED_TASK | 2 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `orch-rescue/20260816T235348-claude-orchestrator-03bd2873` | `03bd28737b` | RECOVERABLE_VALUE | 2 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260817T000016-claude-orchestrator-5d71695e` | `5d71695eba` | RECOVERABLE_VALUE | 1 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260817T000523-claude-orchestrator-54bb1454` | `54bb1454f1` | RECOVERABLE_VALUE | 2 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260817T000523-safe-edit-42706744` | `427067448d` | RECOVERABLE_VALUE | 1 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260817T001041-claude-orchestrator-75d7e08b` | `75d7e08b5e` | RECOVERABLE_VALUE | 2 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260817T001615-claude-orchestrator-63b610a4` | `63b610a479` | RECOVERABLE_VALUE | 2 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260817T002648-claude-orchestrator-7422235e` | `7422235e82` | RECOVERABLE_VALUE | 8 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260817T005618-claude-orchestrator-ee6371c7` | `ee6371c727` | RECOVERABLE_VALUE | 1 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260817T010230-claude-orchestrator-a10db3f9` | `a10db3f93b` | RECOVERABLE_VALUE | 2 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260817T010232-chatgpt-local-reconcile-beethoven-55acd60c79b1-3214adae` | `3214adae9d` | RECOVERABLE_VALUE | 1 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260817T012755-claude-orchestrator-b8b842a0` | `b8b842a03f` | RECOVERABLE_VALUE | 3 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260817T013843-chatgpt-local-reconcile-beethoven-84fc83c513d9-cfdb9ef4` | `cfdb9ef4b6` | RECOVERABLE_VALUE | 1 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260817T014951-claude-orchestrator-8414e002` | `8414e0021e` | RECOVERABLE_VALUE | 3 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260817T014953-chatgpt-local-reconcile-beethoven-84fc83c513d9-7ec82b2c` | `7ec82b2ca9` | RECOVERABLE_VALUE | 1 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `orch-rescue/20260817T015601-chatgpt-local-reconcile-beethoven-8d0702cbd5aa-fb7d0c1d` | `fb7d0c1daa` | RECOVERABLE_VALUE | 2 | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `heads/agent/dropbox-hisanta-mastery-engine-grandma-rail-family-slice-2-clean-129448` | `358297faa1` | CONFLICTED_NEEDS_FOCUSED_TASK | 11 | range diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `heads/agent/improve-missing-branch-auto-creator-slice-3-locate-decomposition-event-handler-a-clean-152441` | `dc65c5428c` | CONFLICTED_NEEDS_FOCUSED_TASK | 4 | range diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `heads/agent/improve-value-aware-test-routing-early-exit-r-slice-3-fix-broken-tests-clean-151469` | `a9e98fc3c7` | CONFLICTED_NEEDS_FOCUSED_TASK | 3 | range diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `heads/fix/session-20260816-repairs` | `75d7e08b5e` | RECOVERABLE_VALUE | 74 | range diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator` | `63b610a479` | RECOVERABLE_VALUE | 557 | 557 uncommitted path(s); tracked diff applies to base. Recover via a new isolated worktree + agent branch. Source worktree left untouched. |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/backlog-batch-beethoven-22ee5bc-convention-conform-slice-2 8309febb` | `1eda33098a` | CONFLICTED_NEEDS_FOCUSED_TASK | 2 | uncommitted tracked diff no longer applies to base; queue a focused follow-up rather than forcing an overwrite |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/backlog-batch-beethoven-22ee5bc-prompt-evolution-bandit-update-claude-interface 67280171` | `76d068867d` | CONFLICTED_NEEDS_FOCUSED_TASK | 2 | uncommitted tracked diff no longer applies to base; queue a focused follow-up rather than forcing an overwrite |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/canary-claude-27-slice-3-adapt-prior-merged-patterns-extract-proven-diffs-extrac 15227eb7` | `ba57d64f0f` | CONFLICTED_NEEDS_FOCUSED_TASK | 2 | uncommitted tracked diff no longer applies to base; queue a focused follow-up rather than forcing an overwrite |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/chatgpt-local-reconcile-beethoven-7b6f925e1e7a` | `d3a6b47abf` | RECOVERABLE_VALUE | 2 | 2 uncommitted path(s); tracked diff applies to base. Recover via a new isolated worktree + agent branch. Source worktree left untouched. |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/chatgpt-local-reconcile-beethoven-ca93a1b7be55` | `d3a6b47abf` | RECOVERABLE_VALUE | 2 | 2 uncommitted path(s); tracked diff applies to base. Recover via a new isolated worktree + agent branch. Source worktree left untouched. |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/never-again-lane-daemon` | `9a14f09438` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | uncommitted tracked diff no longer applies to base; queue a focused follow-up rather than forcing an overwrite |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/spine-types-x2` | `987e5280e7` | RECOVERABLE_VALUE | 1 | 1 untracked new file(s) with no tracked counterpart; review and land through an agent branch. Source left untouched. |
| `/Users/kpasch/Documents/Codex/2026-08-06/figu/work/orchestrator-visibility-remediation` | `fbb735b3cf` | CONFLICTED_NEEDS_FOCUSED_TASK | 17 | uncommitted tracked diff no longer applies to base; queue a focused follow-up rather than forcing an overwrite |
| `/Users/kpasch/Documents/Codex/2026-08-07/cons/work/orchestrator-session-fabric-current` | `59de85f238` | RECOVERABLE_VALUE | 18 | 18 uncommitted path(s); tracked diff applies to base. Recover via a new isolated worktree + agent branch. Source worktree left untouched. |
| `/Users/kpasch/Documents/chatgpt-dropbox/_applied/20260812-020326--claude-orchestrator--operator-output-truth-session-fabric-20260812.patch` | `889cdfd161` | RECOVERABLE_VALUE | 18 | bridge marked this applied, but the patch still applies to origin/master -- the change never reached the default branch. Recover through an agent branch. |
| `/Users/kpasch/Documents/chatgpt-dropbox/_failed/20260807-085521--smarter--apparently-framework-merge.patch` | `6b8f95f50a` | CONFLICTED_NEEDS_FOCUSED_TASK | 68 | failed bridge artifact whose patch no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `snapshot[0] agent/dropbox-hisanta-mastery-engine-grandma-rail-family-slice-2-clean-129448` | `358297faa1` | CONFLICTED_NEEDS_FOCUSED_TASK | 0 | range diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `snapshot[0] agent/improve-missing-branch-auto-creator-slice-3-locate-decomposition-event-handler-a-clean-152441` | `dc65c5428c` | CONFLICTED_NEEDS_FOCUSED_TASK | 0 | range diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `snapshot[0] agent/improve-value-aware-test-routing-early-exit-r-slice-3-fix-broken-tests-clean-151469` | `a9e98fc3c7` | CONFLICTED_NEEDS_FOCUSED_TASK | 0 | range diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `snapshot[1] orch-rescue/20260803T000726-relfix-racefeed-07060650-slice-4` | `9c023d06b7` | CONFLICTED_NEEDS_FOCUSED_TASK | 0 | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `snapshot[2] /Users/kpasch/Documents/Codex/2026-08-07/cons/work/orchestrator-session-fabric` | `` | RECOVERABLE_VALUE | 0 | 1 live row(s) under /Users/kpasch/Documents/Codex/2026-08-07/cons/work/orchestrator-session-fabric; worst-case classification governs the snapshot item |

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

## Provenance for every item with remaining value

- resulting task: `chatgpt-local-reconcile-beethoven-671c267eedf3`
- resulting branch: `agent/chatgpt-local-reconcile-beethoven-671c267eedf3`
- resulting commit: HEAD of that branch, recorded per item in
  `coordination_tasks.commit` under audit fingerprint
  `671c267eedf3f831e2dca9ef7f81cdf779a194fc5bd534e339e471804ce8f004`

Each row below is also a `coordination_tasks` recovery-ledger record keyed
by `(audit_fingerprint, source)`, so the provenance survives this branch.

| source | class | resulting task | resulting branch |
| --- | --- | --- | --- |
| `refs/orch-rescue/20260803T000726-relfix-racefeed-07060650-slice-4` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260803T000752-relfix-racefeed-07060650-slice-4` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260803T001521-relfix-racefeed-07060650-slice-4-ad00f1c9` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260805T145454-deployfix-beethoven-07190338-fix-and-verify-vercel-production-build-423c51ca` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260805T191227-cc-mutual-default-fund-1d7e8d9a` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260805T191228-cc-solvency-passport-6138fffd` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260806T100003-improve-missing-branch-auto-creator-slice-3-locate-decomposition-event-handler-a-bedc007c` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260806T100004-improve-value-aware-test-routing-early-exit-r-slice-3-adapt-merged-patterns-65464532` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260806T131026-improve-value-aware-test-routing-early-exit-r-slice-3-adapt-merged-patterns-d09561bf` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260806T131034-5bee398fbf584c3252b3-57b674c5` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260806T161111-relfix-release-hold-deadlock-cowork-20260806-e9050616` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260806T172735-dropbox-operator-gate-amendment-auto-ship-authoriz-slice-2-9225b0f5` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260806T201809-improve-value-aware-test-routing-early-exit-r-slice-3-fix-broken-tests-ba304347` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260806T202615-improve-value-aware-test-routing-early-exit-r-slice-3-fix-broken-tests-63cf225e` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260806T215726-unbounded-scan-window-class-audit-cowork-20260806-512f19be` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260806T221512-fix-compilation-types-4fb310c6` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260806T224241-improve-upgrade-to-a-high-performance-database-slice-3-integrate-new-module-aa3c1231` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260806T224945-relfix-racefeed-07060650-fix-typescript-and-build--slice-4-fix-missing-branch-7d9bd79d` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260807T015247-dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-p4-releasetrain-vercel-9c79f8f6` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260807T125256-orchestrator-visibility-remediation-15d8c552` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260807T130647-orchestrator-visibility-remediation-a05140c3` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260807T173615-claude-orchestrator-12001806` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260807T220546-improve-automate-branch-management-slice-3-310c54b3` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260808T040916-improve-immediate-auto-merge-on-test-pass-low-r-slice-3-implement-test-completio-7bf524c4` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260808T184515-cade-mirror-negotiation-5d33743e` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260808T184519-canary-claude-27-slice-3-update-tests-checks-analyze-patch-behavior-analyze-patc-a4a7ec82` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260811T152527-orchestrator-session-fabric-current-364b3d7a` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260813T034449-orchestrator-session-fabric-current-7ba40cac` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260813T045320-reconcile-beethoven-55acd60c-ed040682` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260813T063106-chatgpt-local-reconcile-beethoven-6c8911116873-36ff050f` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260813T072604-chatgpt-local-reconcile-beethoven-215fba971ab9-e48843cd` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260813T072605-chatgpt-local-reconcile-beethoven-4d83819ff744-e48843cd` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260813T072605-chatgpt-local-reconcile-beethoven-797668765dad-e48843cd` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260813T080048-chatgpt-local-reconcile-beethoven-ac93979d6c7a-1da71dac` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260813T081746-chatgpt-local-reconcile-beethoven-e0945946bd0d-45fefc8b` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260813T083737-chatgpt-local-reconcile-beethoven-383306e1301e-633e1610` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260813T084725-fix-canonical-enqueue-trigger-regression-20260812-7bf01722` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260813T085137-fix-canonical-enqueue-trigger-regression-20260812-cd80d50c` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260813T091206-chatgpt-local-reconcile-beethoven-3b50d1e569de-d0ecb81c` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260813T102021-chatgpt-local-reconcile-beethoven-5e30d0e05126-4ecfa8aa` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260813T102021-chatgpt-local-reconcile-beethoven-84fc83c513d9-4ecfa8aa` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260813T201101-pinned-express-814604f7` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260813T201603-pinned-express-dcf328aa` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260813T202224-pinned-express-739d0d24` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260813T205213-dropbox-beethoven-audit-addendum-two-session-reconciliation-read-wit-group-5-3213f4fa` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260813T213903-dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-3-speed-triage-routing-accelerators-p0-28c0982f` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260813T233826-c27-minimal-680be7c7` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260813T234327-c27-minimal-649efcae` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260814T001818-canary-claude-27-slice-1-run-checks-90a1e704` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260814T043640-backlog-batch-beethoven-a86bb21-recover-pinned-exp-slice-1-26b72d0b` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260814T044159-backlog-batch-beethoven-a86bb21-recover-pinned-exp-slice-1-50dd28e3` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260814T045028-dropbox-recover-lease-night-g1-95167518` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260814T045639-backlog-batch-beethoven-d3151d8-d2055a73` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260814T050204-backlog-batch-beethoven-d3151d8-87d761c1` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260815T155037-backlog-batch-beethoven-a86bb21-recover-pinned-exp-slice-1-3568709e` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260815T155824-backlog-batch-beethoven-a86bb21-recover-pinned-exp-slice-1-519f71f7` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260815T160343-backlog-batch-beethoven-a86bb21-recover-pinned-exp-slice-1-6383c3a4` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260815T160936-backlog-batch-beethoven-a86bb21-recover-pinned-exp-slice-1-fb89ac45` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260815T171020-claude-orchestrator-03d90b53` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260815T180824-canary-gemini-25-canary-gemini-25-setup-install-dependencies-7171a247` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260815T181331-canary-gemini-25-canary-gemini-25-setup-install-dependencies-97ff52d0` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260815T181909-canary-gemini-25-canary-gemini-25-setup-install-dependencies-ea35b8b0` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260815T185730-claude-orchestrator-f43954f3` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260815T194812-claude-orchestrator-ca7e84ca` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260815T195439-claude-orchestrator-ebc35563` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260815T200110-canary-gemini-25-canary-gemini-25-setup-install-dependencies-85fe983d` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260815T201040-dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-batch-fusion-unpause-f728f655` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260815T202759-canary-gemini-25-canary-gemini-25-setup-install-dependencies-c74d8a5f` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260815T215740-claude-orchestrator-f935294a` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260815T224825-claude-orchestrator-bf19be4d` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260815T230027-claude-orchestrator-f049ff3b` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260815T230608-claude-orchestrator-6beec314` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260815T230609-chatgpt-local-reconcile-beethoven-fa219072749e-06d3b538` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260815T231152-chatgpt-local-reconcile-beethoven-fa219072749e-0efcd03c` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260815T233403-claude-orchestrator-b8ad611d` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260815T235049-claude-orchestrator-060c1f47` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260816T225433-claude-orchestrator-9ed89d5f` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260816T230458-safe-edit-e6b8d2b8` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260816T231100-safe-edit-768fbf8d` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260816T231604-claude-orchestrator-ef07b604` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260816T234850-claude-orchestrator-2b12f025` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260816T235348-claude-orchestrator-03bd2873` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260817T000016-claude-orchestrator-5d71695e` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260817T000523-claude-orchestrator-54bb1454` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260817T000523-safe-edit-42706744` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260817T001041-claude-orchestrator-75d7e08b` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260817T001615-claude-orchestrator-63b610a4` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260817T002648-claude-orchestrator-7422235e` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260817T005618-claude-orchestrator-ee6371c7` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260817T010230-claude-orchestrator-a10db3f9` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260817T010232-chatgpt-local-reconcile-beethoven-55acd60c79b1-3214adae` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260817T012755-claude-orchestrator-b8b842a0` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260817T013843-chatgpt-local-reconcile-beethoven-84fc83c513d9-cfdb9ef4` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260817T014951-claude-orchestrator-8414e002` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260817T014953-chatgpt-local-reconcile-beethoven-84fc83c513d9-7ec82b2c` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/orch-rescue/20260817T015601-chatgpt-local-reconcile-beethoven-8d0702cbd5aa-fb7d0c1d` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/heads/agent/dropbox-hisanta-mastery-engine-grandma-rail-family-slice-2-clean-129448` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/heads/agent/improve-missing-branch-auto-creator-slice-3-locate-decomposition-event-handler-a-clean-152441` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/heads/agent/improve-value-aware-test-routing-early-exit-r-slice-3-fix-broken-tests-clean-151469` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `refs/heads/fix/session-20260816-repairs` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/backlog-batch-beethoven-22ee5bc-convention-conform-slice-2 8309febb` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/backlog-batch-beethoven-22ee5bc-prompt-evolution-bandit-update-claude-interface 67280171` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/canary-claude-27-slice-3-adapt-prior-merged-patterns-extract-proven-diffs-extrac 15227eb7` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/chatgpt-local-reconcile-beethoven-7b6f925e1e7a` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/chatgpt-local-reconcile-beethoven-ca93a1b7be55` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/never-again-lane-daemon` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/spine-types-x2` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `/Users/kpasch/Documents/Codex/2026-08-06/figu/work/orchestrator-visibility-remediation` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `/Users/kpasch/Documents/Codex/2026-08-07/cons/work/orchestrator-session-fabric-current` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `/Users/kpasch/Documents/chatgpt-dropbox/_applied/20260812-020326--claude-orchestrator--operator-output-truth-session-fabric-20260812.patch` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `/Users/kpasch/Documents/chatgpt-dropbox/_failed/20260807-085521--smarter--apparently-framework-merge.patch` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `snapshot[0] agent/dropbox-hisanta-mastery-engine-grandma-rail-family-slice-2-clean-129448` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `snapshot[0] agent/improve-missing-branch-auto-creator-slice-3-locate-decomposition-event-handler-a-clean-152441` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `snapshot[0] agent/improve-value-aware-test-routing-early-exit-r-slice-3-fix-broken-tests-clean-151469` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `snapshot[1] refs/orch-rescue/20260803T000726-relfix-racefeed-07060650-slice-4` | CONFLICTED_NEEDS_FOCUSED_TASK | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
| `snapshot[2] /Users/kpasch/Documents/Codex/2026-08-07/cons/work/orchestrator-session-fabric` | RECOVERABLE_VALUE | `chatgpt-local-reconcile-beethoven-671c267eedf3` | `agent/chatgpt-local-reconcile-beethoven-671c267eedf3` |
