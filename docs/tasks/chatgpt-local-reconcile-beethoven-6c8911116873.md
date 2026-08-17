# chatgpt-local-reconcile-beethoven-6c8911116873

Reconciliation of local ChatGPT/Codex build evidence for `beethoven` against
`origin/master`, under audit fingerprint `6c8911116873878c82a862a05e9412b770e354c83e9c0779d761418a5352bbc5`.

The evidence source was treated as strictly read-only. Nothing was stashed, popped,
dropped, reset, cleaned, checked out, pruned or moved. Every ref, worktree and patch
named below is still exactly where the snapshot found it. The one write outside this
branch was additive: the previous unpushed attempt tip was copied to
`refs/orch-preserved/chatgpt-local-reconcile-beethoven-6c8911116873-attempt-prior` before the agent
branch was re-pointed at `origin/master`, so that attempt is still reachable.

## Method — prior art, not a rewrite

| step | tool | already in the repo |
| --- | --- | --- |
| live enumeration + classification | `tools/reconcile_all_evidence.py` (drives `reconcile_rescue_refs.py`, `reconcile_local_branches.py`, `reconcile_worktree_evidence.py`) | yes |
| snapshot-to-live mapping | `tools/map_snapshot_evidence.mjs` | added here |
| ledger publication | `tools/recovery_ledger_publish.py` | yes |

The task snapshot is a digest plus a sample, so the live source was enumerated
directly and is authoritative. The snapshot entries are then mapped onto it, one
ledger row each, so a ref that has since been pushed (and therefore drops out of the
local-only pass) is still adjudicated instead of silently disappearing.

## Result

Ledger: `.orch/recovery-ledger-6c8911116873.json` — **646 evidence items, 0 UNKNOWN**.

| classification | count |
| --- | ---: |
| ALREADY_PRESENT | 220 |
| SUPERSEDED_BY_NEWER | 309 |
| ACTIVE_IN_ANOTHER_TASK | 12 |
| RECOVERABLE_VALUE | 57 |
| CONFLICTED_NEEDS_FOCUSED_TASK | 48 |
| **UNKNOWN** | **0** |

### By evidence kind

| kind | already | superseded | active | recoverable | conflicted |
| --- | ---: | ---: | ---: | ---: | ---: |
| `broken_codex_git_worktree` | 1 | 0 | 0 | 0 | 0 |
| `chatgpt_bridge_artifact` | 0 | 0 | 0 | 1 | 0 |
| `codex_output_artifact` | 0 | 0 | 0 | 0 | 1 |
| `dirty_worktree` | 18 | 0 | 0 | 7 | 5 |
| `local_only_branch_tips` | 12 | 6 | 2 | 1 | 3 |
| `orchestrator_rescue_refs` | 188 | 285 | 10 | 48 | 35 |
| `snapshot:dirty_worktree` | 0 | 0 | 0 | 0 | 1 |
| `snapshot:local_only_branch_tips` | 1 | 18 | 0 | 0 | 3 |

## Items with remaining value

Every row below is carried by this task: branch `agent/chatgpt-local-reconcile-beethoven-6c8911116873`,
commit: the tip of that branch, recorded verbatim in every `coordination_tasks` row. The evidence itself is untouched — the disposition records where
the value is routed, never an instruction to delete the source.

### RECOVERABLE_VALUE (57)

Disposition for all of these: the ref/worktree stays exactly where it is, and recovery
goes through a normal agent branch + merge train — one focused branch per item, never a
bulk replay over newer code. None is applied in place.

| source | kind | sha | disposition |
| --- | --- | --- | --- |
| `refs/orch-rescue/20260805T145454-deployfix-beethoven-07190338-fix-and-verify-vercel-production-build-423c51ca` | orchestrator_rescue_refs | `423c51ca9ad9` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260806T100003-improve-missing-branch-auto-creator-slice-3-locate-decomposition-event-handler-a-bedc007c` | orchestrator_rescue_refs | `bedc007cc039` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260806T100004-improve-value-aware-test-routing-early-exit-r-slice-3-adapt-merged-patterns-65464532` | orchestrator_rescue_refs | `6546453246a8` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260806T224241-improve-upgrade-to-a-high-performance-database-slice-3-integrate-new-module-aa3c1231` | orchestrator_rescue_refs | `aa3c12313899` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260807T173615-claude-orchestrator-12001806` | orchestrator_rescue_refs | `12001806dfbc` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260811T152527-orchestrator-session-fabric-current-364b3d7a` | orchestrator_rescue_refs | `364b3d7a0410` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260813T034449-orchestrator-session-fabric-current-7ba40cac` | orchestrator_rescue_refs | `7ba40cacae3b` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260813T045320-reconcile-beethoven-55acd60c-ed040682` | orchestrator_rescue_refs | `ed0406825fc8` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260813T084725-fix-canonical-enqueue-trigger-regression-20260812-7bf01722` | orchestrator_rescue_refs | `7bf017227df0` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260813T085137-fix-canonical-enqueue-trigger-regression-20260812-cd80d50c` | orchestrator_rescue_refs | `cd80d50c9498` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260813T213903-dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-3-speed-triage-routing-accelerators-p0-28c0982f` | orchestrator_rescue_refs | `28c0982f84cf` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260813T233826-c27-minimal-680be7c7` | orchestrator_rescue_refs | `680be7c71c2e` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260813T234327-c27-minimal-649efcae` | orchestrator_rescue_refs | `649efcae3b71` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260814T043640-backlog-batch-beethoven-a86bb21-recover-pinned-exp-slice-1-26b72d0b` | orchestrator_rescue_refs | `26b72d0b1a66` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260814T045028-dropbox-recover-lease-night-g1-95167518` | orchestrator_rescue_refs | `951675184a85` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260814T045639-backlog-batch-beethoven-d3151d8-d2055a73` | orchestrator_rescue_refs | `d2055a738b27` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260814T050204-backlog-batch-beethoven-d3151d8-87d761c1` | orchestrator_rescue_refs | `87d761c1abd1` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260815T155037-backlog-batch-beethoven-a86bb21-recover-pinned-exp-slice-1-3568709e` | orchestrator_rescue_refs | `3568709ebd39` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260815T155824-backlog-batch-beethoven-a86bb21-recover-pinned-exp-slice-1-519f71f7` | orchestrator_rescue_refs | `519f71f716fc` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260815T160343-backlog-batch-beethoven-a86bb21-recover-pinned-exp-slice-1-6383c3a4` | orchestrator_rescue_refs | `6383c3a493fe` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260815T160936-backlog-batch-beethoven-a86bb21-recover-pinned-exp-slice-1-fb89ac45` | orchestrator_rescue_refs | `fb89ac4547fb` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260815T171020-claude-orchestrator-03d90b53` | orchestrator_rescue_refs | `03d90b53027e` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260815T185730-claude-orchestrator-f43954f3` | orchestrator_rescue_refs | `f43954f34532` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260815T194812-claude-orchestrator-ca7e84ca` | orchestrator_rescue_refs | `ca7e84ca0c35` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260815T195439-claude-orchestrator-ebc35563` | orchestrator_rescue_refs | `ebc355630f18` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260815T201040-dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-batch-fusion-unpause-f728f655` | orchestrator_rescue_refs | `f728f6558ed6` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260815T202759-canary-gemini-25-canary-gemini-25-setup-install-dependencies-c74d8a5f` | orchestrator_rescue_refs | `c74d8a5f5939` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260815T215740-claude-orchestrator-f935294a` | orchestrator_rescue_refs | `f935294ae926` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260815T224825-claude-orchestrator-bf19be4d` | orchestrator_rescue_refs | `bf19be4d0c20` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260815T230027-claude-orchestrator-f049ff3b` | orchestrator_rescue_refs | `f049ff3bbc07` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260815T230608-claude-orchestrator-6beec314` | orchestrator_rescue_refs | `6beec3143c72` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260815T230609-chatgpt-local-reconcile-beethoven-fa219072749e-06d3b538` | orchestrator_rescue_refs | `06d3b5384d66` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260815T231152-chatgpt-local-reconcile-beethoven-fa219072749e-0efcd03c` | orchestrator_rescue_refs | `0efcd03cb0f6` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260815T233403-claude-orchestrator-b8ad611d` | orchestrator_rescue_refs | `b8ad611d8c12` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260815T235049-claude-orchestrator-060c1f47` | orchestrator_rescue_refs | `060c1f47466f` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260816T225433-claude-orchestrator-9ed89d5f` | orchestrator_rescue_refs | `9ed89d5fe44f` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260816T231100-safe-edit-768fbf8d` | orchestrator_rescue_refs | `768fbf8d3df0` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260816T231604-claude-orchestrator-ef07b604` | orchestrator_rescue_refs | `ef07b6040b1b` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260816T235348-claude-orchestrator-03bd2873` | orchestrator_rescue_refs | `03bd28737bad` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260817T000016-claude-orchestrator-5d71695e` | orchestrator_rescue_refs | `5d71695ebaef` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260817T000523-claude-orchestrator-54bb1454` | orchestrator_rescue_refs | `54bb1454f1f7` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260817T000523-safe-edit-42706744` | orchestrator_rescue_refs | `427067448dd4` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260817T001041-claude-orchestrator-75d7e08b` | orchestrator_rescue_refs | `75d7e08b5e41` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260817T001615-claude-orchestrator-63b610a4` | orchestrator_rescue_refs | `63b610a47960` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260817T002648-claude-orchestrator-7422235e` | orchestrator_rescue_refs | `7422235e8232` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260817T005618-claude-orchestrator-ee6371c7` | orchestrator_rescue_refs | `ee6371c7279c` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260817T010230-claude-orchestrator-a10db3f9` | orchestrator_rescue_refs | `a10db3f93b92` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/orch-rescue/20260817T010232-chatgpt-local-reconcile-beethoven-55acd60c79b1-3214adae` | orchestrator_rescue_refs | `3214adae9d7b` | diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `refs/heads/fix/session-20260816-repairs` | local_only_branch_tips | `75d7e08b5e41` | range diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator` | dirty_worktree | `63b610a47960` | 550 uncommitted path(s); tracked diff applies to base. Recover via a new isolated worktree + agent branch. Source worktree left untouched. |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/chatgpt-local-reconcile-beethoven-179a43b4d07a` | dirty_worktree | `d3a6b47abff4` | 1 untracked new file(s) with no tracked counterpart; review and land through an agent branch. Source left untouched. |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/chatgpt-local-reconcile-beethoven-3b50d1e569de` | dirty_worktree | `d3a6b47abff4` | 1 untracked new file(s) with no tracked counterpart; review and land through an agent branch. Source left untouched. |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/chatgpt-local-reconcile-beethoven-84fc83c513d9` | dirty_worktree | `d3a6b47abff4` | 1 untracked new file(s) with no tracked counterpart; review and land through an agent branch. Source left untouched. |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/chatgpt-local-reconcile-beethoven-8d0702cbd5aa` | dirty_worktree | `d3a6b47abff4` | 1 untracked new file(s) with no tracked counterpart; review and land through an agent branch. Source left untouched. |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/spine-types-x2` | dirty_worktree | `987e5280e7bf` | 1 untracked new file(s) with no tracked counterpart; review and land through an agent branch. Source left untouched. |
| `/Users/kpasch/Documents/Codex/2026-08-07/cons/work/orchestrator-session-fabric-current` | dirty_worktree | `59de85f238e6` | 18 uncommitted path(s); tracked diff applies to base. Recover via a new isolated worktree + agent branch. Source worktree left untouched. |
| `/Users/kpasch/Documents/chatgpt-dropbox/_applied/20260812-020326--claude-orchestrator--operator-output-truth-session-fabric-20260812.patch` | chatgpt_bridge_artifact | `889cdfd16140` | bridge marked this applied, but the patch still applies to origin/master -- the change never reached the default branch. Recover through an agent branch. |

### CONFLICTED_NEEDS_FOCUSED_TASK (48)

Disposition for all of these: queue a focused follow-up. None is forced onto
`origin/master`, because each either fails an apply-check against the current base or
is a snapshot ref with no base, no remote and no live counterpart. Overwriting on a
guess is the failure mode this classification exists to prevent.

| source | kind | sha | disposition |
| --- | --- | --- | --- |
| `refs/orch-rescue/20260803T000726-relfix-racefeed-07060650-slice-4` | orchestrator_rescue_refs | `9c023d06b744` | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `refs/orch-rescue/20260803T000752-relfix-racefeed-07060650-slice-4` | orchestrator_rescue_refs | `5152ab956fb3` | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `refs/orch-rescue/20260803T001521-relfix-racefeed-07060650-slice-4-ad00f1c9` | orchestrator_rescue_refs | `ad00f1c964f5` | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `refs/orch-rescue/20260805T191227-cc-mutual-default-fund-1d7e8d9a` | orchestrator_rescue_refs | `1d7e8d9a0f5d` | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `refs/orch-rescue/20260805T191228-cc-solvency-passport-6138fffd` | orchestrator_rescue_refs | `6138fffd679c` | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `refs/orch-rescue/20260806T131026-improve-value-aware-test-routing-early-exit-r-slice-3-adapt-merged-patterns-d09561bf` | orchestrator_rescue_refs | `d09561bff005` | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `refs/orch-rescue/20260806T131034-5bee398fbf584c3252b3-57b674c5` | orchestrator_rescue_refs | `57b674c55724` | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `refs/orch-rescue/20260806T161111-relfix-release-hold-deadlock-cowork-20260806-e9050616` | orchestrator_rescue_refs | `e9050616befb` | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `refs/orch-rescue/20260806T172735-dropbox-operator-gate-amendment-auto-ship-authoriz-slice-2-9225b0f5` | orchestrator_rescue_refs | `9225b0f5075c` | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `refs/orch-rescue/20260806T201809-improve-value-aware-test-routing-early-exit-r-slice-3-fix-broken-tests-ba304347` | orchestrator_rescue_refs | `ba3043475fca` | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `refs/orch-rescue/20260806T202615-improve-value-aware-test-routing-early-exit-r-slice-3-fix-broken-tests-63cf225e` | orchestrator_rescue_refs | `63cf225ebc23` | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `refs/orch-rescue/20260806T215726-unbounded-scan-window-class-audit-cowork-20260806-512f19be` | orchestrator_rescue_refs | `512f19be8216` | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `refs/orch-rescue/20260806T221512-fix-compilation-types-4fb310c6` | orchestrator_rescue_refs | `4fb310c6e68d` | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `refs/orch-rescue/20260806T224945-relfix-racefeed-07060650-fix-typescript-and-build--slice-4-fix-missing-branch-7d9bd79d` | orchestrator_rescue_refs | `7d9bd79d372c` | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `refs/orch-rescue/20260807T015247-dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-p4-releasetrain-vercel-9c79f8f6` | orchestrator_rescue_refs | `9c79f8f60c72` | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `refs/orch-rescue/20260807T125256-orchestrator-visibility-remediation-15d8c552` | orchestrator_rescue_refs | `15d8c55228a0` | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `refs/orch-rescue/20260807T130647-orchestrator-visibility-remediation-a05140c3` | orchestrator_rescue_refs | `a05140c32f0b` | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `refs/orch-rescue/20260807T220546-improve-automate-branch-management-slice-3-310c54b3` | orchestrator_rescue_refs | `310c54b33510` | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `refs/orch-rescue/20260808T040916-improve-immediate-auto-merge-on-test-pass-low-r-slice-3-implement-test-completio-7bf524c4` | orchestrator_rescue_refs | `7bf524c47597` | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `refs/orch-rescue/20260808T184515-cade-mirror-negotiation-5d33743e` | orchestrator_rescue_refs | `5d33743e8008` | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `refs/orch-rescue/20260808T184519-canary-claude-27-slice-3-update-tests-checks-analyze-patch-behavior-analyze-patc-a4a7ec82` | orchestrator_rescue_refs | `a4a7ec82a395` | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `refs/orch-rescue/20260813T063106-chatgpt-local-reconcile-beethoven-6c8911116873-36ff050f` | orchestrator_rescue_refs | `36ff050f9d06` | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `refs/orch-rescue/20260813T081746-chatgpt-local-reconcile-beethoven-e0945946bd0d-45fefc8b` | orchestrator_rescue_refs | `45fefc8b7855` | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `refs/orch-rescue/20260813T201101-pinned-express-814604f7` | orchestrator_rescue_refs | `814604f710d1` | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `refs/orch-rescue/20260813T201603-pinned-express-dcf328aa` | orchestrator_rescue_refs | `dcf328aaa8d1` | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `refs/orch-rescue/20260813T202224-pinned-express-739d0d24` | orchestrator_rescue_refs | `739d0d249fbe` | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `refs/orch-rescue/20260813T205213-dropbox-beethoven-audit-addendum-two-session-reconciliation-read-wit-group-5-3213f4fa` | orchestrator_rescue_refs | `3213f4fa8fa9` | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `refs/orch-rescue/20260814T001818-canary-claude-27-slice-1-run-checks-90a1e704` | orchestrator_rescue_refs | `90a1e70413b0` | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `refs/orch-rescue/20260814T044159-backlog-batch-beethoven-a86bb21-recover-pinned-exp-slice-1-50dd28e3` | orchestrator_rescue_refs | `50dd28e3866f` | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `refs/orch-rescue/20260815T180824-canary-gemini-25-canary-gemini-25-setup-install-dependencies-7171a247` | orchestrator_rescue_refs | `7171a24710af` | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `refs/orch-rescue/20260815T181331-canary-gemini-25-canary-gemini-25-setup-install-dependencies-97ff52d0` | orchestrator_rescue_refs | `97ff52d03ea0` | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `refs/orch-rescue/20260815T181909-canary-gemini-25-canary-gemini-25-setup-install-dependencies-ea35b8b0` | orchestrator_rescue_refs | `ea35b8b0d4fc` | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `refs/orch-rescue/20260815T200110-canary-gemini-25-canary-gemini-25-setup-install-dependencies-85fe983d` | orchestrator_rescue_refs | `85fe983d3de4` | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `refs/orch-rescue/20260816T230458-safe-edit-e6b8d2b8` | orchestrator_rescue_refs | `e6b8d2b8e06c` | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `refs/orch-rescue/20260816T234850-claude-orchestrator-2b12f025` | orchestrator_rescue_refs | `2b12f02518b1` | diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `refs/heads/agent/dropbox-hisanta-mastery-engine-grandma-rail-family-slice-2-clean-129448` | local_only_branch_tips | `358297faa18f` | range diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `refs/heads/agent/improve-missing-branch-auto-creator-slice-3-locate-decomposition-event-handler-a-clean-152441` | local_only_branch_tips | `dc65c5428c7c` | range diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `refs/heads/agent/improve-value-aware-test-routing-early-exit-r-slice-3-fix-broken-tests-clean-151469` | local_only_branch_tips | `a9e98fc3c705` | range diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/backlog-batch-beethoven-22ee5bc-convention-conform-slice-2 8309febb` | dirty_worktree | `1eda33098a1e` | uncommitted tracked diff no longer applies to base; queue a focused follow-up rather than forcing an overwrite |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/backlog-batch-beethoven-22ee5bc-prompt-evolution-bandit-update-claude-interface 67280171` | dirty_worktree | `76d068867dc2` | uncommitted tracked diff no longer applies to base; queue a focused follow-up rather than forcing an overwrite |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/canary-claude-27-slice-3-adapt-prior-merged-patterns-extract-proven-diffs-extrac 15227eb7` | dirty_worktree | `ba57d64f0fb4` | uncommitted tracked diff no longer applies to base; queue a focused follow-up rather than forcing an overwrite |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/never-again-lane-daemon` | dirty_worktree | `9a14f0943855` | uncommitted tracked diff no longer applies to base; queue a focused follow-up rather than forcing an overwrite |
| `/Users/kpasch/Documents/Codex/2026-08-06/figu/work/orchestrator-visibility-remediation` | dirty_worktree | `fbb735b3cfe4` | uncommitted tracked diff no longer applies to base; queue a focused follow-up rather than forcing an overwrite |
| `/Users/kpasch/Documents/chatgpt-dropbox/_failed/20260807-085521--smarter--apparently-framework-merge.patch` | codex_output_artifact | `6b8f95f50a07` | failed bridge artifact whose patch no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `snapshot[0] /Users/kpasch/Documents/beethoven/claude-orchestrator` | snapshot:dirty_worktree | `af6b89dc3ff3` | 27 live row(s) under /Users/kpasch/Documents/beethoven/claude-orchestrator; worst-case classification governs the snapshot item |
| `snapshot[1] agent/dropbox-hisanta-mastery-engine-grandma-rail-family-slice-2-clean-129448` | snapshot:local_only_branch_tips | `358297faa18f` | range diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `snapshot[1] agent/improve-missing-branch-auto-creator-slice-3-locate-decomposition-event-handler-a-clean-152441` | snapshot:local_only_branch_tips | `dc65c5428c7c` | range diff no longer applies; queue a focused follow-up rather than forcing an overwrite |
| `snapshot[1] agent/improve-value-aware-test-routing-early-exit-r-slice-3-fix-broken-tests-clean-151469` | snapshot:local_only_branch_tips | `a9e98fc3c705` | range diff no longer applies; queue a focused follow-up rather than forcing an overwrite |

## Coordination ledger

One `coordination_tasks` record per evidence item (646 rows), `task_type =
recovery_ledger`, keyed by the audit fingerprint above and carrying source,
classification, disposition and the resulting task/branch/commit. Published with
`tools/recovery_ledger_publish.py`, which is idempotent on
`(audit_fingerprint, source)`.

## Tests

`node --test tools/map_snapshot_evidence.test.mjs` — 8/8 pass.
