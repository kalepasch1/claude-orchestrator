# ChatGPT/Codex local build-evidence reconciliation — beethoven

Audit fingerprint: `ed3b33e3e884cac2dcb94ab4bf44f65e890a44369a0b4d0a05e46e8aa107eece`

Base: `origin/master` @ `817651866444` · generated 2026-09-10T09:45:01.794Z

Regenerate with:

```bash
node scripts/reconcile-rescue-refs.mjs --base origin/master \
  --fingerprint ed3b33e3e884cac2dcb94ab4bf44f65e890a44369a0b4d0a05e46e8aa107eece \
  --out docs/recovery-ledger-ed3b33e3e884.json
node scripts/recovery-ledger-report.mjs --ledger docs/recovery-ledger-ed3b33e3e884.json --project beethoven
```

## Result

**791 evidence items classified, 0 UNKNOWN.** The evidence source was treated as read-only throughout — nothing was deleted, reset, cleaned, popped or moved. Classification is recomputed from live refs, not from the snapshot in the task prompt.

| Classification | Count | Disposition |
|---|---:|---|
| CONFLICTED_NEEDS_FOCUSED_TASK | 150 | queue a focused conflict-resolution task; never force-overwrite |
| ACTIVE_IN_ANOTHER_TASK | 35 | no action — leave to the owning branch/task; do not duplicate |
| SUPERSEDED_BY_NEWER | 365 | no action — newer implementation on the default branch wins |
| ALREADY_PRESENT | 241 | no action — value already on the default branch |

## Items with remaining value

150 item(s) below keep durable provenance in `docs/recovery-ledger-ed3b33e3e884.json` (source ref, sha, subject, touched files, carrier branches). None were applied in this pass — per the coordination rule, conflicts get a focused follow-up rather than a forced overwrite.

| Source ref | Class | Files | Subject |
|---|---|---:|---|
| `20260910T093839-claude-orchestrator-f9ae47e0` | CONFLICTED_NEEDS_FOCUSED_TASK | 203 | On master: orch-rescue: periodic sweep |
| `20260910T083359-claude-orchestrator-7f16733f` | CONFLICTED_NEEDS_FOCUSED_TASK | 198 | On master: orch-rescue: periodic sweep |
| `20260910T062438-chatgpt-local-reconcile-beethoven-8f8b9616a104-900b00ab` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | On agent/chatgpt-local-reconcile-beethoven-8f8b9616a104: orch-rescue: periodic s |
| `20260910T061940-chatgpt-local-reconcile-beethoven-2074293bd139-140fed81` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | On agent/chatgpt-local-reconcile-beethoven-2074293bd139: orch-rescue: periodic s |
| `20260910T055748-chatgpt-local-reconcile-beethoven-0ce4c6e8284c-649d31d1` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | On agent/chatgpt-local-reconcile-beethoven-0ce4c6e8284c: orch-rescue: periodic s |
| `20260910T055231-chatgpt-local-reconcile-beethoven-c870b59c7ec8-63cb1ecb` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | On agent/chatgpt-local-reconcile-beethoven-c870b59c7ec8: orch-rescue: periodic s |
| `20260910T054727-5bee398fbf584c3252b3-run-13355-1789018958949518000-cc905f06` | CONFLICTED_NEEDS_FOCUSED_TASK | 6 | On agent/recovered-src-orchestrator-layout-decision: orch-rescue: periodic sweep |
| `20260910T054716-chatgpt-local-reconcile-beethoven-f7b45f3f90ad-f9051965` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | On agent/chatgpt-local-reconcile-beethoven-f7b45f3f90ad: orch-rescue: periodic s |
| `20260910T054147-5bee398fbf584c3252b3-run-12904-1789017170771328000-3f61fa74` | CONFLICTED_NEEDS_FOCUSED_TASK | 6 | On agent/chatgpt-local-reconcile-beethoven-169a0a07fa18: orch-rescue: periodic s |
| `20260910T050151-chatgpt-local-reconcile-beethoven-a8452a1f6114-54c1da1e` | CONFLICTED_NEEDS_FOCUSED_TASK | 3 | On agent/chatgpt-local-reconcile-beethoven-a8452a1f6114: orch-rescue: periodic s |
| `20260910T044820-reconcile-169a0a07fa18-ec0e5a3e` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | On (no branch): orch-rescue: periodic sweep |
| `20260910T043026-reconcile-4a838e298f31-fix-baffc82b` | CONFLICTED_NEEDS_FOCUSED_TASK | 6 | On (no branch): orch-rescue: periodic sweep |
| `20260910T042524-reconcile-4a838e298f31-fix-728d06ec` | CONFLICTED_NEEDS_FOCUSED_TASK | 6 | On (no branch): orch-rescue: periodic sweep |
| `20260910T041527-reconcile-4a838e298f31-fix-01edfc63` | CONFLICTED_NEEDS_FOCUSED_TASK | 5 | On (no branch): orch-rescue: periodic sweep |
| `20260910T035234-5bee398fbf584c3252b3-run-45103-1789012272538850000-cecd9909` | CONFLICTED_NEEDS_FOCUSED_TASK | 165 | On (no branch): orch-rescue: periodic sweep |
| `20260910T033654-5bee398fbf584c3252b3-run-21029-1789011128447381000-fa0d70ab` | CONFLICTED_NEEDS_FOCUSED_TASK | 170 | On agent/chatgpt-local-reconcile-beethoven-4a838e298f31: orch-rescue: periodic s |
| `20260910T032531-5bee398fbf584c3252b3-run-37358-1789010621489233000-6135d0f5` | CONFLICTED_NEEDS_FOCUSED_TASK | 165 | On (no branch): orch-rescue: periodic sweep |
| `20260910T031939-5bee398fbf584c3252b3-run-77426-1789009975086531000-eb62634d` | CONFLICTED_NEEDS_FOCUSED_TASK | 165 | On (no branch): orch-rescue: periodic sweep |
| `20260910T031934-repair-childless-decompositions-blocking-operator-queue-88bd9141` | CONFLICTED_NEEDS_FOCUSED_TASK | 4 | On agent/repair-childless-decompositions-blocking-operator-queue: orch-rescue: p |
| `20260910T030511-5bee398fbf584c3252b3-run-63902-1789008776749582000-92621276` | CONFLICTED_NEEDS_FOCUSED_TASK | 165 | On (no branch): orch-rescue: periodic sweep |
| `20260910T030510-5bee398fbf584c3252b3-run-62570-1789009324519936000-443e04c8` | CONFLICTED_NEEDS_FOCUSED_TASK | 165 | On (no branch): orch-rescue: periodic sweep |
| `20260910T030507-5bee398fbf584c3252b3-run-3655-1789009053933550000-263cb559` | CONFLICTED_NEEDS_FOCUSED_TASK | 165 | On (no branch): orch-rescue: periodic sweep |
| `20260910T021411-5bee398fbf584c3252b3-run-10174-1789006255919577000-b7a6f810` | CONFLICTED_NEEDS_FOCUSED_TASK | 165 | On (no branch): orch-rescue: periodic sweep |
| `20260910T015038-5bee398fbf584c3252b3-run-3609-1789004891514587000-82373037` | CONFLICTED_NEEDS_FOCUSED_TASK | 165 | On (no branch): orch-rescue: periodic sweep |
| `20260910T014218-5bee398fbf584c3252b3-run-22252-1789004300579885000-602daca1` | CONFLICTED_NEEDS_FOCUSED_TASK | 165 | On (no branch): orch-rescue: periodic sweep |
| `20260910T013118-5bee398fbf584c3252b3-run-48291-1789003690994293000-3d413042` | CONFLICTED_NEEDS_FOCUSED_TASK | 166 | On agent/dropbox-beethoven-core-integrity-audit-merge-safet-slice-2: orch-rescue |
| `20260910T013114-5bee398fbf584c3252b3-run-28351-1789003478402549000-cbd30e35` | CONFLICTED_NEEDS_FOCUSED_TASK | 165 | On (no branch): orch-rescue: periodic sweep |
| `20260910T013051-canary-pin-dba45dc4` | CONFLICTED_NEEDS_FOCUSED_TASK | 165 | On (no branch): orch-rescue: periodic sweep |
| `20260910T013040-repair-childless-decompositions-blocking-operator-queue-70d623d0` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | On agent/repair-childless-decompositions-blocking-operator-queue: orch-rescue: p |
| `20260910T011734-5bee398fbf584c3252b3-run-82529-1789002874021424000-0b810f4c` | CONFLICTED_NEEDS_FOCUSED_TASK | 162 | On (no branch): orch-rescue: periodic sweep |
| `20260910T011732-5bee398fbf584c3252b3-run-29227-1789002578368772000-eee74e33` | CONFLICTED_NEEDS_FOCUSED_TASK | 160 | On (no branch): orch-rescue: periodic sweep |
| `20260910T011728-canary-pin-4adf2cf8` | CONFLICTED_NEEDS_FOCUSED_TASK | 162 | On (no branch): orch-rescue: periodic sweep |
| `20260910T010539-5bee398fbf584c3252b3-run-96830-1789000937237836000-dc3155f5` | CONFLICTED_NEEDS_FOCUSED_TASK | 128 | On (no branch): orch-rescue: periodic sweep |
| `20260910T010537-5bee398fbf584c3252b3-run-28519-1789001679715324000-90636a8e` | CONFLICTED_NEEDS_FOCUSED_TASK | 139 | On (no branch): orch-rescue: periodic sweep |
| `20260910T010533-canary-pin-bc7c91e1` | CONFLICTED_NEEDS_FOCUSED_TASK | 142 | On (no branch): orch-rescue: periodic sweep |
| `20260910T010513-chatgpt-local-reconcile-beethoven-4ca585bf4ce0-cba65cfa` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | On agent/chatgpt-local-reconcile-beethoven-4ca585bf4ce0: orch-rescue: periodic s |
| `20260910T003136-5bee398fbf584c3252b3-run-67776-1788998826259073000-76c89792` | CONFLICTED_NEEDS_FOCUSED_TASK | 26 | On (no branch): orch-rescue: periodic sweep |
| `20260910T001022-5bee398fbf584c3252b3-run-22882-1788997154962532000-20228df8` | CONFLICTED_NEEDS_FOCUSED_TASK | 10 | On (no branch): orch-rescue: periodic sweep |
| `20260909T230000-toolchain-worktree-dep-provisioning-decae144` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | On agent/toolchain-worktree-dep-provisioning: orch-rescue: periodic sweep |
| `20260909T224415-5bee398fbf584c3252b3-run-39455-1788993701164351000-ebef9196` | CONFLICTED_NEEDS_FOCUSED_TASK | 10 | On (no branch): orch-rescue: periodic sweep |
| `20260909T222052-5bee398fbf584c3252b3-run-80905-1788992247730390000-4baaa6fc` | CONFLICTED_NEEDS_FOCUSED_TASK | 10 | On (no branch): orch-rescue: periodic sweep |
| `20260909T222044-5bee398fbf584c3252b3-run-20498-1788991902823589000-5fbd281a` | CONFLICTED_NEEDS_FOCUSED_TASK | 10 | On (no branch): orch-rescue: periodic sweep |
| `20260909T215752-5bee398fbf584c3252b3-run-70806-1788990945165864000-196135f8` | CONFLICTED_NEEDS_FOCUSED_TASK | 10 | On (no branch): orch-rescue: periodic sweep |
| `20260909T212351-5bee398fbf584c3252b3-run-14680-1788988257593359000-fa160cba` | CONFLICTED_NEEDS_FOCUSED_TASK | 10 | On (no branch): orch-rescue: periodic sweep |
| `20260909T204938-5bee398fbf584c3252b3-run-80092-1788986771282068000-5805dcaf` | CONFLICTED_NEEDS_FOCUSED_TASK | 10 | On (no branch): orch-rescue: periodic sweep |
| `20260909T194214-5bee398fbf584c3252b3-run-39742-1788982797607290000-fee850f7` | CONFLICTED_NEEDS_FOCUSED_TASK | 10 | On (no branch): orch-rescue: periodic sweep |
| `20260909T192002-5bee398fbf584c3252b3-run-52732-1788981523627594000-066ad203` | CONFLICTED_NEEDS_FOCUSED_TASK | 10 | On (no branch): orch-rescue: periodic sweep |
| `20260909T185258-5bee398fbf584c3252b3-run-63399-1788978790703814000-5b450b7f` | CONFLICTED_NEEDS_FOCUSED_TASK | 10 | On (no branch): orch-rescue: periodic sweep |
| `20260909T185251-5bee398fbf584c3252b3-run-30575-1788979862007131000-9e8681af` | CONFLICTED_NEEDS_FOCUSED_TASK | 10 | On (no branch): orch-rescue: periodic sweep |
| `20260909T183001-5bee398fbf584c3252b3-run-20229-1788978117199968000-701a84fe` | CONFLICTED_NEEDS_FOCUSED_TASK | 10 | On (no branch): orch-rescue: periodic sweep |
| `20260909T175709-5bee398fbf584c3252b3-run-44623-1788975902303450000-2ea23f43` | CONFLICTED_NEEDS_FOCUSED_TASK | 10 | On (no branch): orch-rescue: periodic sweep |
| `20260909T173913-5bee398fbf584c3252b3-run-84412-1788974948201421000-09860a40` | CONFLICTED_NEEDS_FOCUSED_TASK | 10 | On (no branch): orch-rescue: periodic sweep |
| `20260909T173912-5bee398fbf584c3252b3-run-66180-1788975395379442000-5987dfe6` | CONFLICTED_NEEDS_FOCUSED_TASK | 10 | On (no branch): orch-rescue: periodic sweep |
| `20260909T172720-5bee398fbf584c3252b3-run-88404-1788974281017743000-5e360285` | CONFLICTED_NEEDS_FOCUSED_TASK | 10 | On (no branch): orch-rescue: periodic sweep |
| `20260909T172719-5bee398fbf584c3252b3-run-52718-1788974027622641000-b571f49a` | CONFLICTED_NEEDS_FOCUSED_TASK | 10 | On (no branch): orch-rescue: periodic sweep |
| `20260909T171250-5bee398fbf584c3252b3-run-68570-1788972997038720000-3bbaa990` | CONFLICTED_NEEDS_FOCUSED_TASK | 10 | On (no branch): orch-rescue: periodic sweep |
| `20260909T165556-5bee398fbf584c3252b3-run-99492-1788972183690050000-5464a5c2` | CONFLICTED_NEEDS_FOCUSED_TASK | 10 | On (no branch): orch-rescue: periodic sweep |
| `20260909T155812-5bee398fbf584c3252b3-run-24735-1788969128060907000-fab7191f` | CONFLICTED_NEEDS_FOCUSED_TASK | 18 | On agent/dropbox-pareto-life-goal-autonomy-stack-p2-delegation-firewall: orch-re |
| `20260909T155704-claude-orchestrator-ac51ae8c` | CONFLICTED_NEEDS_FOCUSED_TASK | 10 | On master: orch-rescue: periodic sweep |
| `20260909T154756-improve-improve-orchestration-with-ai-ml-for-dyn-slice-4-4ba191ce` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | task: improve-improve-orchestration-with-ai-ml-for-dyn-slice-4 |
| `20260909T154742-improve-automated-branch-management-with-gitops-slice-1-4cd3d60f` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | task: improve-automated-branch-management-with-gitops-slice-1 |
| `20260909T154755-improve-implement-real-time-sync-between-web-and-slice-4-bd27545d` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | task: improve-implement-real-time-sync-between-web-and-slice-4 |
| `20260909T154753-improve-enhanced-testing-infrastructure-slice-4-9dc7c00d` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | task: improve-enhanced-testing-infrastructure-slice-4 |
| `20260909T152638-claude-orchestrator-7a476b84` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | On master: orch-rescue: periodic sweep |
| `20260909T151052-5bee398fbf584c3252b3-run-6139-1788966431398720000-82833d33` | CONFLICTED_NEEDS_FOCUSED_TASK | 10 | On (no branch): orch-rescue: periodic sweep |
| `20260909T145227-5bee398fbf584c3252b3-run-75398-1788965032925518000-890feb9f` | CONFLICTED_NEEDS_FOCUSED_TASK | 12 | On agent/dropbox-release-pipeline-completion-windows-half-l-slice-2-review-and-r |
| `20260909T145156-claude-orchestrator-c7643cfd` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | On master: orch-rescue: periodic sweep |
| `20260909T143247-5bee398fbf584c3252b3-run-86217-1788964277765202000-4ef92eeb` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | On (no branch): orch-rescue: periodic sweep |
| `20260909T142656-5bee398fbf584c3252b3-run-98952-1788963756749237000-d8a9ca0c` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | On (no branch): orch-rescue: periodic sweep |
| `20260909T142200-5bee398fbf584c3252b3-run-22874-1788961533327893000-bf76da41` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | On (no branch): orch-rescue: periodic sweep |
| `20260909T133505-5bee398fbf584c3252b3-run-23929-1788960691320279000-4f8c4841` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | On (no branch): orch-rescue: periodic sweep |
| `20260909T132842-improve-improve-orchestration-with-ai-ml-for-dyn-slice-4-b5978208` | CONFLICTED_NEEDS_FOCUSED_TASK | 8 | task: improve-improve-orchestration-with-ai-ml-for-dyn-slice-4 |
| `20260909T125049-5bee398fbf584c3252b3-run-16627-1788957581309763000-bdb05a5c` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | On (no branch): orch-rescue: periodic sweep |
| `20260909T122938-improve-automated-branch-management-with-gitops-slice-1-11da635f` | CONFLICTED_NEEDS_FOCUSED_TASK | 8 | task: improve-automated-branch-management-with-gitops-slice-1 |
| `20260909T122941-improve-implement-real-time-sync-between-web-and-slice-4-117a7c24` | CONFLICTED_NEEDS_FOCUSED_TASK | 8 | task: improve-implement-real-time-sync-between-web-and-slice-4 |
| `20260909T122940-improve-enhanced-testing-infrastructure-slice-4-bbc5f606` | CONFLICTED_NEEDS_FOCUSED_TASK | 8 | task: improve-enhanced-testing-infrastructure-slice-4 |
| `20260909T121254-claude-orchestrator-3581ce58` | CONFLICTED_NEEDS_FOCUSED_TASK | 8 | On master: orch-rescue: periodic sweep |
| `20260909T104359-5bee398fbf584c3252b3-run-17138-1788950452240178000-cf096bae` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | On (no branch): orch-rescue: periodic sweep |
| `20260909T100458-5bee398fbf584c3252b3-run-39102-1788947783906985000-2cf67a76` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | On (no branch): orch-rescue: periodic sweep |
| `20260909T095402-5bee398fbf584c3252b3-run-2682-1788947514759938000-266fc6d4` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | On (no branch): orch-rescue: periodic sweep |
| `20260909T095401-5bee398fbf584c3252b3-run-2682-1788947087542695000-24a4a615` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | On (no branch): orch-rescue: periodic sweep |
| `20260909T095325-claude-orchestrator-b270b854` | CONFLICTED_NEEDS_FOCUSED_TASK | 8 | On master: orch-rescue: periodic sweep |
| `20260909T094229-5bee398fbf584c3252b3-run-2705-1788946476943965000-ac9f3d59` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | On (no branch): orch-rescue: periodic sweep |
| `20260909T083546-5bee398fbf584c3252b3-run-5141-1788942277859007000-bc1c598a` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | On (no branch): orch-rescue: periodic sweep |
| `20260909T080909-5bee398fbf584c3252b3-run-57416-1788941073051068000-12efe06f` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | On (no branch): orch-rescue: periodic sweep |
| `20260909T075151-5bee398fbf584c3252b3-run-4854-1788940115440189000-7d8561b3` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | On (no branch): orch-rescue: periodic sweep |
| `20260909T074105-5bee398fbf584c3252b3-run-60021-1788939519886975000-f8dedcd0` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | On (no branch): orch-rescue: periodic sweep |
| `20260909T065825-5bee398fbf584c3252b3-run-90679-1788936819525760000-bc8e90d6` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | On (no branch): orch-rescue: periodic sweep |
| `20260909T063017-relfix-identity-daa307d4` | CONFLICTED_NEEDS_FOCUSED_TASK | 17 | On agent/relfix-tomorrow-09090552: orch-rescue: periodic sweep |
| `20260909T062026-5bee398fbf584c3252b3-run-62391-1788934084200059000-1fde5d39` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | On (no branch): orch-rescue: periodic sweep |
| `20260909T054309-5bee398fbf584c3252b3-run-57309-1788931317076138000-18c7d5eb` | CONFLICTED_NEEDS_FOCUSED_TASK | 10 | On agent/dropbox-prompt-merged-diff-memory-system-task-spec-group-7-split-the-bu |
| `20260909T054256-fullsuite-wt-d911a891` | CONFLICTED_NEEDS_FOCUSED_TASK | 3 | On (no branch): orch-rescue: periodic sweep |
| `20260909T053454-dropbox-release-pipeline-completion-windows-half-l-slice-2-ensure-test-dependenc-9a13a684` | CONFLICTED_NEEDS_FOCUSED_TASK | 3 | On agent/dropbox-release-pipeline-completion-windows-half-l-slice-2-ensure-test- |
| `20260909T053448-claude-orchestrator-db5d2124` | CONFLICTED_NEEDS_FOCUSED_TASK | 8 | On master: orch-rescue: periodic sweep |
| `20260909T051747-oauth-refresh-fix-04d559e7` | CONFLICTED_NEEDS_FOCUSED_TASK | 3 | On agent/dropbox-release-pipeline-completion-windows-half-l-slice-2-fix-the-auth |
| `20260909T051200-chatgpt-local-reconcile-beethoven-c59669efa6f0-65218e2c` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | On agent/chatgpt-local-reconcile-beethoven-c59669efa6f0: orch-rescue: periodic s |
| `20260909T044919-reconcile-f8c1bb486dd1-587e3029` | CONFLICTED_NEEDS_FOCUSED_TASK | 2 | On agent/chatgpt-local-reconcile-beethoven-f8c1bb486dd1: orch-rescue: periodic s |
| `20260909T043656-dropbox-release-pipeline-completion-windows-half-l-slice-2-ensure-test-dependenc-b57ed629` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | On agent/dropbox-release-pipeline-completion-windows-half-l-slice-2-ensure-test- |
| `20260908T175539-claude-orchestrator-2d139500` | CONFLICTED_NEEDS_FOCUSED_TASK | 4 | On master: orch-rescue: periodic sweep |
| `20260908T172055-claude-orchestrator-e3e08c51` | CONFLICTED_NEEDS_FOCUSED_TASK | 4 | On master: orch-rescue: periodic sweep |
| `20260908T170523-claude-orchestrator-39352a1d` | CONFLICTED_NEEDS_FOCUSED_TASK | 4 | On master: orch-rescue: periodic sweep |
| `20260908T165746-claude-orchestrator-49a30723` | CONFLICTED_NEEDS_FOCUSED_TASK | 4 | On master: orch-rescue: periodic sweep |
| `20260908T164830-5eed4d232cc6fd3c7073-run-66824-1788871359866084000-9e78c704` | CONFLICTED_NEEDS_FOCUSED_TASK | 4 | On master: orch-rescue: periodic sweep |
| `20260908T154147-claude-orchestrator-8fc77607` | CONFLICTED_NEEDS_FOCUSED_TASK | 4 | On master: orch-rescue: periodic sweep |
| `20260908T131112-claude-orchestrator-0f02b4f6` | CONFLICTED_NEEDS_FOCUSED_TASK | 4 | On master: orch-rescue: periodic sweep |
| `20260908T125618-claude-orchestrator-7529f6bd` | CONFLICTED_NEEDS_FOCUSED_TASK | 4 | On master: orch-rescue: periodic sweep |
| `20260908T113337-canary-self-deploy-live-slice-1-a044eac5` | CONFLICTED_NEEDS_FOCUSED_TASK | 3 | On agent/canary-self-deploy-live-slice-1: orch-rescue: periodic sweep |
| `20260908T103426-5eed4d232cc6fd3c7073-run-30631-1788863358914671000-903c899b` | CONFLICTED_NEEDS_FOCUSED_TASK | 4 | On master: orch-rescue: periodic sweep |
| `20260908T094656-claude-orchestrator-aa94af48` | CONFLICTED_NEEDS_FOCUSED_TASK | 4 | On master: orch-rescue: periodic sweep |
| `20260908T044436-claude-orchestrator-3816093c` | CONFLICTED_NEEDS_FOCUSED_TASK | 3 | On master: orch-rescue: periodic sweep |
| `20260908T042342-rework-legal-cont-batch-darwn-277f0bd-9657042-2585e8a9` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | On agent/rework-legal-cont-batch-darwn-277f0bd-9657042: orch-rescue: periodic sw |
| `20260908T035809-5eed4d232cc6fd3c7073-run-47517-1788838750934723000-ac45f706` | CONFLICTED_NEEDS_FOCUSED_TASK | 4 | On master: orch-rescue: periodic sweep |
| `20260908T031542-claude-orchestrator-01358045` | CONFLICTED_NEEDS_FOCUSED_TASK | 4 | On master: orch-rescue: periodic sweep |
| `20260908T015513-5eed4d232cc6fd3c7073-run-3041-1788817957903261000-70fd1950` | CONFLICTED_NEEDS_FOCUSED_TASK | 12 | On orchestrator/dev: orch-rescue: periodic sweep |
| `20260908T014446-claude-orchestrator-f48e34e6` | CONFLICTED_NEEDS_FOCUSED_TASK | 12 | On orchestrator/dev: orch-rescue: periodic sweep |
| `20260908T011037-claude-orchestrator-aca90551` | CONFLICTED_NEEDS_FOCUSED_TASK | 11 | On master: orch-rescue: periodic sweep |
| `20260908T005236-claude-orchestrator-ca1fb88a` | CONFLICTED_NEEDS_FOCUSED_TASK | 12 | On master: orch-rescue: periodic sweep |
| `20260908T002327-5bee398fbf584c3252b3-run-95881-1788824413096639000-e73b6317` | CONFLICTED_NEEDS_FOCUSED_TASK | 695 | On (no branch): orch-rescue: periodic sweep |
| `20260907T231316-claude-orchestrator-32c8f523` | CONFLICTED_NEEDS_FOCUSED_TASK | 12 | On master: orch-rescue: periodic sweep |
| `20260907T094809-claude-orchestrator-3c2c1905` | CONFLICTED_NEEDS_FOCUSED_TASK | 12 | On master: orch-rescue: periodic sweep |
| `20260907T074827-claude-orchestrator-434a3056` | CONFLICTED_NEEDS_FOCUSED_TASK | 11 | On master: orch-rescue: periodic sweep |
| `20260907T034421-oc-autoclear-policy-713dd094` | CONFLICTED_NEEDS_FOCUSED_TASK | 10 | On agent/oc-autoclear-policy: orch-rescue: periodic sweep |
| `20260907T014930-claude-orchestrator-43739da8` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | On master: orch-rescue: periodic sweep |
| `20260906T235543-claude-orchestrator-4940675d` | CONFLICTED_NEEDS_FOCUSED_TASK | 2 | On master: orch-rescue: periodic sweep |
| `20260906T234525-claude-orchestrator-67c9d1c7` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | On master: orch-rescue: periodic sweep |
| `20260906T200352-claude-orchestrator-e01fb802` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | On master: orch-rescue: periodic sweep |
| `20260906T164414-claude-orchestrator-24aed9ab` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | On master: orch-rescue: periodic sweep |
| `20260906T161418-claude-orchestrator-3e872779` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | On master: orch-rescue: periodic sweep |
| `20260906T095231-claude-orchestrator-ba41be2f` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | On master: orch-rescue: periodic sweep |
| `20260905T204901-claude-orchestrator-2392b4f3` | CONFLICTED_NEEDS_FOCUSED_TASK | 2 | On master: orch-rescue: periodic sweep |
| `20260905T103553-claude-orchestrator-4963a6d1` | CONFLICTED_NEEDS_FOCUSED_TASK | 4 | On master: orch-rescue: periodic sweep |
| `20260905T010131-5bee398fbf584c3252b3-run-92737-1788569735363546000-5e594bee` | CONFLICTED_NEEDS_FOCUSED_TASK | 436 | On (no branch): orch-rescue: periodic sweep |
| `20260904T225118-5eed4d232cc6fd3c7073-run-8121-1788561957999088000-86f60544` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | On master: orch-rescue: periodic sweep |
| `20260904T223023-claude-orchestrator-c0dcfd83` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | On master: orch-rescue: periodic sweep |
| `20260904T203607-claude-orchestrator-1c8270ae` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | On master: orch-rescue: periodic sweep |
| `20260904T090425-5bee398fbf584c3252b3-run-67150-1788512392138289000-3de71a0c` | CONFLICTED_NEEDS_FOCUSED_TASK | 2 | agent: dropbox-prompt-merged-diff-memory-system-task-spec-group-7 |
| `20260904T075528-5bee398fbf584c3252b3-run-29208-1788508027427749000-60cc6111` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | feat(replay): add the periodic pass that turns replay into routing policy |
| `20260817T035301-chatgpt-local-reconcile-beethoven-85d2de799d5d-6c8ea700` | CONFLICTED_NEEDS_FOCUSED_TASK | 2 | On agent/chatgpt-local-reconcile-beethoven-85d2de799d5d: orch-rescue: periodic s |
| `20260817T020836-chatgpt-local-reconcile-beethoven-ca93a1b7be55-e6107650` | CONFLICTED_NEEDS_FOCUSED_TASK | 2 | On agent/chatgpt-local-reconcile-beethoven-ca93a1b7be55: orch-rescue: periodic s |
| `20260817T020832-chatgpt-local-reconcile-beethoven-7b6f925e1e7a-2e4c82d4` | CONFLICTED_NEEDS_FOCUSED_TASK | 2 | On agent/chatgpt-local-reconcile-beethoven-7b6f925e1e7a: orch-rescue: periodic s |
| `20260817T020154-chatgpt-local-reconcile-beethoven-671c267eedf3-74b8aed7` | CONFLICTED_NEEDS_FOCUSED_TASK | 2 | On agent/chatgpt-local-reconcile-beethoven-671c267eedf3: orch-rescue: periodic s |
| `20260817T015601-chatgpt-local-reconcile-beethoven-8d0702cbd5aa-fb7d0c1d` | CONFLICTED_NEEDS_FOCUSED_TASK | 2 | On agent/chatgpt-local-reconcile-beethoven-8d0702cbd5aa: orch-rescue: periodic s |
| `20260815T181331-canary-gemini-25-canary-gemini-25-setup-install-dependencies-97ff52d0` | CONFLICTED_NEEDS_FOCUSED_TASK | 3 | On agent/canary-gemini-25-canary-gemini-25-setup-install-dependencies: orch-resc |
| `20260815T180824-canary-gemini-25-canary-gemini-25-setup-install-dependencies-7171a247` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | On agent/canary-gemini-25-canary-gemini-25-setup-install-dependencies: orch-resc |
| `20260814T050204-backlog-batch-beethoven-d3151d8-87d761c1` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | On agent/backlog-batch-beethoven-d3151d8: orch-rescue: periodic sweep |
| `20260814T045639-backlog-batch-beethoven-d3151d8-d2055a73` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | On agent/backlog-batch-beethoven-d3151d8: orch-rescue: periodic sweep |
| `20260814T045028-dropbox-recover-lease-night-g1-95167518` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | On agent/dropbox-recover-the-lease-night-stash-work-branch-hotfix-stash-rescu-gr |
| `20260813T234327-c27-minimal-649efcae` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | On (no branch): orch-rescue: periodic sweep |
| `20260813T233826-c27-minimal-680be7c7` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | On (no branch): orch-rescue: periodic sweep |
| `20260805T145454-deployfix-beethoven-07190338-fix-and-verify-vercel-production-build-423c51ca` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | On agent/deployfix-beethoven-07190338-fix-and-verify-vercel-production-build: or |

## Notes

- `ACTIVE_IN_ANOTHER_TASK` items are already carried by a live `agent/*` branch; re-applying them here would duplicate queued work.
- `SUPERSEDED_BY_NEWER` is decided by commit time on the base for every source file the rescue commit touches — the newest/most complete implementation wins.
- Refs whose only content is generated (`node_modules`, `.vite`, `.nuxt`, `dist`, `coverage`, …) are classified `ALREADY_PRESENT`: a vitest cache is build noise, not lost work, and must not spawn a follow-up task that can never produce a meaningful diff.
