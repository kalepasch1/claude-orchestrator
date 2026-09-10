# ChatGPT/Codex local build-evidence reconciliation — beethoven

Audit fingerprint: `4ca585bf4ce02b94ebeb2cd44862ade7e98be519870045036a3a457f15bad765`

Base: `origin/orchestrator/dev` @ `bcacf428ecb1` · generated 2026-09-10T01:07:35.885Z

Regenerate with:

```bash
node tools/reconcile-local-evidence.mjs --kind rescue-refs \
  --base origin/orchestrator/dev \
  --fingerprint 4ca585bf4ce02b94ebeb2cd44862ade7e98be519870045036a3a457f15bad765 \
  --json docs/recovery/ledger-4ca585bf4ce0-rescue.json
node scripts/recovery-ledger-report.mjs --ledger docs/recovery/ledger-4ca585bf4ce0-rescue.json --project beethoven
```

## Result

**734 evidence items classified, 0 UNKNOWN.** The evidence source was treated as read-only throughout — nothing was deleted, reset, cleaned, popped or moved. Classification is recomputed from live refs, not from the snapshot in the task prompt.

| Classification | Count | Disposition |
|---|---:|---|
| CONFLICTED_NEEDS_FOCUSED_TASK | 148 | queue a focused conflict-resolution task; never force-overwrite |
| ACTIVE_IN_ANOTHER_TASK | 323 | no action — leave to the owning branch/task; do not duplicate |
| SUPERSEDED_BY_NEWER | 28 | no action — newer implementation on the default branch wins |
| ALREADY_PRESENT | 235 | no action — value already on the default branch |

## Items with remaining value

148 item(s) below keep durable provenance in `docs/recovery/ledger-4ca585bf4ce0-rescue.json` (source ref, sha, subject, touched files, carrier branches). None were applied in this pass — per the coordination rule, conflicts get a focused follow-up rather than a forced overwrite.

| Source ref | Class | Files | Subject |
|---|---|---:|---|
| `20260803T000726-relfix-racefeed-07060650-slice-4` | CONFLICTED_NEEDS_FOCUSED_TASK | 4 | On fix-branch: orch-rescue: periodic sweep |
| `20260803T000752-relfix-racefeed-07060650-slice-4` | CONFLICTED_NEEDS_FOCUSED_TASK | 4 | On fix-branch: orch-rescue: periodic sweep |
| `20260803T001521-relfix-racefeed-07060650-slice-4-ad00f1c9` | CONFLICTED_NEEDS_FOCUSED_TASK | 4 | On fix-branch: orch-rescue: periodic sweep |
| `20260811T152527-orchestrator-session-fabric-current-364b3d7a` | CONFLICTED_NEEDS_FOCUSED_TASK | 15 | On codex/orchestrator-session-fabric: orch-rescue: periodic sweep |
| `20260813T034449-orchestrator-session-fabric-current-7ba40cac` | CONFLICTED_NEEDS_FOCUSED_TASK | 18 | On codex/orchestrator-session-fabric: orch-rescue: periodic sweep |
| `20260813T070224-chatgpt-local-reconcile-beethoven-e4b9212494ba-7abaa1b7` | CONFLICTED_NEEDS_FOCUSED_TASK | 7 | On agent/chatgpt-local-reconcile-beethoven-e4b9212494ba: orch-rescue: periodic s |
| `20260813T072604-chatgpt-local-reconcile-beethoven-215fba971ab9-e48843cd` | CONFLICTED_NEEDS_FOCUSED_TASK | 7 | agent: reconcile-evidence — .patch/.diff bridge artifacts + receipt-based branch |
| `20260813T072605-chatgpt-local-reconcile-beethoven-4d83819ff744-e48843cd` | CONFLICTED_NEEDS_FOCUSED_TASK | 7 | agent: reconcile-evidence — .patch/.diff bridge artifacts + receipt-based branch |
| `20260813T072605-chatgpt-local-reconcile-beethoven-797668765dad-e48843cd` | CONFLICTED_NEEDS_FOCUSED_TASK | 7 | agent: reconcile-evidence — .patch/.diff bridge artifacts + receipt-based branch |
| `20260813T080048-chatgpt-local-reconcile-beethoven-ac93979d6c7a-1da71dac` | CONFLICTED_NEEDS_FOCUSED_TASK | 8 | agent: chatgpt-local-reconcile-beethoven-e4b9212494ba |
| `20260813T083737-chatgpt-local-reconcile-beethoven-383306e1301e-633e1610` | CONFLICTED_NEEDS_FOCUSED_TASK | 10 | agent: chatgpt-local-reconcile-beethoven-e0945946bd0d |
| `20260813T091206-chatgpt-local-reconcile-beethoven-3b50d1e569de-d0ecb81c` | CONFLICTED_NEEDS_FOCUSED_TASK | 11 | agent: chatgpt-local-reconcile-beethoven-383306e1301e |
| `20260813T102021-chatgpt-local-reconcile-beethoven-5e30d0e05126-4ecfa8aa` | CONFLICTED_NEEDS_FOCUSED_TASK | 12 | agent: chatgpt-local-reconcile-beethoven-3b50d1e569de |
| `20260813T102021-chatgpt-local-reconcile-beethoven-84fc83c513d9-4ecfa8aa` | CONFLICTED_NEEDS_FOCUSED_TASK | 12 | agent: chatgpt-local-reconcile-beethoven-3b50d1e569de |
| `20260813T231931-backlog-batch-beethoven-22ee5bc-convention-conform-slice-2-8309febb-1eda3309` | CONFLICTED_NEEDS_FOCUSED_TASK | 58 | agent: backlog-batch-beethoven-a86bb21-recover-economic-scheduler-revenue-fix-ec |
| `20260813T231932-backlog-batch-beethoven-22ee5bc-prompt-evolution-bandit-update-claude-interface-67280171-76d06886` | CONFLICTED_NEEDS_FOCUSED_TASK | 58 | agent: backlog-batch-beethoven-a86bb21-recover-economic-scheduler-revenue-fix-ec |
| `20260813T231932-canary-claude-27-slice-3-adapt-prior-merged-patterns-extract-proven-diffs-extrac-15227eb7-ba57d64f` | CONFLICTED_NEEDS_FOCUSED_TASK | 58 | agent: backlog-batch-beethoven-a86bb21-recover-economic-scheduler-revenue-fix-ec |
| `20260813T233826-c27-minimal-680be7c7` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | On (no branch): orch-rescue: periodic sweep |
| `20260813T234327-c27-minimal-649efcae` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | On (no branch): orch-rescue: periodic sweep |
| `20260814T045028-dropbox-recover-lease-night-g1-95167518` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | On agent/dropbox-recover-the-lease-night-stash-work-branch-hotfix-stash-rescu-gr |
| `20260816T230458-safe-edit-e6b8d2b8` | CONFLICTED_NEEDS_FOCUSED_TASK | 674 | On fix/preflight-substantial-specs: orch-rescue: periodic sweep |
| `20260816T231100-safe-edit-768fbf8d` | CONFLICTED_NEEDS_FOCUSED_TASK | 31 | On fix/session-20260816-repairs: orch-rescue: periodic sweep |
| `20260817T000523-safe-edit-42706744` | CONFLICTED_NEEDS_FOCUSED_TASK | 59 | On fix/session-20260816-repairs: orch-rescue: periodic sweep |
| `20260817T020832-chatgpt-local-reconcile-beethoven-7b6f925e1e7a-2e4c82d4` | CONFLICTED_NEEDS_FOCUSED_TASK | 2 | On agent/chatgpt-local-reconcile-beethoven-7b6f925e1e7a: orch-rescue: periodic s |
| `20260819T013753-reconcile-wt-2b229a51` | CONFLICTED_NEEDS_FOCUSED_TASK | 5 | On (no branch): orch-rescue: periodic sweep |
| `20260901T144210-5bee398fbf584c3252b3-55a7693a` | CONFLICTED_NEEDS_FOCUSED_TASK | 385 | On (no branch): orch-rescue: periodic sweep |
| `20260902T010756-5bee398fbf584c3252b3-040fda95` | CONFLICTED_NEEDS_FOCUSED_TASK | 28 | On (no branch): orch-rescue: periodic sweep |
| `20260902T011959-claude-orchestrator-5d4c01eb` | CONFLICTED_NEEDS_FOCUSED_TASK | 35 | fix(preopt): advisory model calls had write access to the orchestrator's own tre |
| `20260902T112623-5bee398fbf584c3252b3-run-10089-1788347009456346000-83bbd88a` | CONFLICTED_NEEDS_FOCUSED_TASK | 3932 | On (no branch): orch-rescue: periodic sweep |
| `20260902T220057-canary-pin-87b70ea1` | CONFLICTED_NEEDS_FOCUSED_TASK | 1121 | On (no branch): orch-rescue: periodic sweep |
| `20260903T205751-claude-orchestrator-2e3fbeb2` | CONFLICTED_NEEDS_FOCUSED_TASK | 7 | Merge branch 'agent/chatgpt-local-reconcile-beethoven-03d851526d1e' (auto-resolv |
| `20260903T224727-minimal-task-gnyhzfcc-748846d3` | CONFLICTED_NEEDS_FOCUSED_TASK | 3273 | On (no branch): orch-rescue: periodic sweep |
| `20260903T224757-5bee398fbf584c3252b3-run-84045-1788475165585027000-d981e8a9` | CONFLICTED_NEEDS_FOCUSED_TASK | 225 | On (no branch): orch-rescue: periodic sweep |
| `20260903T233208-5bee398fbf584c3252b3-run-55598-1788478008717656000-b8d9189a` | CONFLICTED_NEEDS_FOCUSED_TASK | 225 | On (no branch): orch-rescue: periodic sweep |
| `20260904T001811-5bee398fbf584c3252b3-run-83585-1788480575538227000-98d9424d` | CONFLICTED_NEEDS_FOCUSED_TASK | 132 | On (no branch): orch-rescue: periodic sweep |
| `20260904T010109-5bee398fbf584c3252b3-run-14287-1788483406144596000-77f3946b` | CONFLICTED_NEEDS_FOCUSED_TASK | 2144 | On (no branch): orch-rescue: periodic sweep |
| `20260904T014341-5bee398fbf584c3252b3-run-67826-1788485993271122000-43cd7250` | CONFLICTED_NEEDS_FOCUSED_TASK | 358 | On (no branch): orch-rescue: periodic sweep |
| `20260904T024606-5bee398fbf584c3252b3-run-72149-1788489433337543000-40509a11` | CONFLICTED_NEEDS_FOCUSED_TASK | 330 | On (no branch): orch-rescue: periodic sweep |
| `20260904T032520-5bee398fbf584c3252b3-run-15926-1788492149678019000-4afbf6f3` | CONFLICTED_NEEDS_FOCUSED_TASK | 2549 | On (no branch): orch-rescue: periodic sweep |
| `20260904T041031-5bee398fbf584c3252b3-run-70327-1788494953423110000-a07d5c12` | CONFLICTED_NEEDS_FOCUSED_TASK | 379 | On (no branch): orch-rescue: periodic sweep |
| `20260904T043201-minimal-task-hvh32mig-34a1d64e` | CONFLICTED_NEEDS_FOCUSED_TASK | 3417 | On (no branch): orch-rescue: periodic sweep |
| `20260904T050419-5bee398fbf584c3252b3-run-17732-1788497626241820000-dfce64d8` | CONFLICTED_NEEDS_FOCUSED_TASK | 402 | On (no branch): orch-rescue: periodic sweep |
| `20260904T053439-5bee398fbf584c3252b3-run-61697-1788499947595714000-a71c0f2b` | CONFLICTED_NEEDS_FOCUSED_TASK | 225 | On (no branch): orch-rescue: periodic sweep |
| `20260904T062421-5bee398fbf584c3252b3-run-61697-1788499947595714000-f5e9ad7c` | CONFLICTED_NEEDS_FOCUSED_TASK | 4 | agent: fix-canary-recreate-loop-20260825-nq31 |
| `20260904T062422-5bee398fbf584c3252b3-run-70327-1788494953423110000-84c1c07d` | CONFLICTED_NEEDS_FOCUSED_TASK | 2 | agent: improve-improved-ci-cd-pipeline-integration-slice-1-ensure-patch-template |
| `20260904T075528-5bee398fbf584c3252b3-run-29208-1788508027427749000-60cc6111` | CONFLICTED_NEEDS_FOCUSED_TASK | 1 | feat(replay): add the periodic pass that turns replay into routing policy |
| `20260904T083727-5bee398fbf584c3252b3-run-82798-1788510671234112000-b1984ab9` | CONFLICTED_NEEDS_FOCUSED_TASK | 223 | On (no branch): orch-rescue: periodic sweep |
| `20260904T090412-canary-deepseek-1-a9fa358e` | CONFLICTED_NEEDS_FOCUSED_TASK | 17 | Merge branch 'agent/dropbox-prompt-merged-diff-memory-system-task-spec-group-12' |
| `20260904T090425-5bee398fbf584c3252b3-run-67150-1788512392138289000-3de71a0c` | CONFLICTED_NEEDS_FOCUSED_TASK | 2 | agent: dropbox-prompt-merged-diff-memory-system-task-spec-group-7 |
| `20260904T103737-5bee398fbf584c3252b3-run-62844-1788516131936712000-5f3fa197` | CONFLICTED_NEEDS_FOCUSED_TASK | 3 | agent: dropbox-beethoven-core-integrity-audit-merge-safety-self-protection--grou |
| `20260904T111414-5bee398fbf584c3252b3-run-97248-1788520086531033000-2b995804` | CONFLICTED_NEEDS_FOCUSED_TASK | 133 | On (no branch): orch-rescue: periodic sweep |
| `20260904T114410-5bee398fbf584c3252b3-run-69068-1788522082754622000-d844cf5b` | CONFLICTED_NEEDS_FOCUSED_TASK | 3 | agent: dropbox-release-pipeline-completion-windows-half-l-slice-4 |
| `20260904T115006-canary-deepseek-1-a8218d4f` | CONFLICTED_NEEDS_FOCUSED_TASK | 25 | Stop failing good code because the test gate cannot find npm |
| `20260904T120724-5bee398fbf584c3252b3-run-30056-1788523339916287000-48f323f1` | CONFLICTED_NEEDS_FOCUSED_TASK | 133 | On (no branch): orch-rescue: periodic sweep |
| `20260904T120726-5bee398fbf584c3252b3-run-52856-1788523619870446000-37806d2e` | CONFLICTED_NEEDS_FOCUSED_TASK | 133 | On (no branch): orch-rescue: periodic sweep |
| `20260904T125414-5bee398fbf584c3252b3-run-93874-1788526121138468000-ec4e4d64` | CONFLICTED_NEEDS_FOCUSED_TASK | 133 | On (no branch): orch-rescue: periodic sweep |
| `20260904T125948-5bee398fbf584c3252b3-run-53700-1788526611821670000-90fd8f3b` | CONFLICTED_NEEDS_FOCUSED_TASK | 133 | On (no branch): orch-rescue: periodic sweep |
| `20260904T131642-5bee398fbf584c3252b3-run-89626-1788527672530357000-d5584459` | CONFLICTED_NEEDS_FOCUSED_TASK | 133 | On (no branch): orch-rescue: periodic sweep |
| `20260904T133352-5bee398fbf584c3252b3-run-35487-1788528285025170000-f3a436cf` | CONFLICTED_NEEDS_FOCUSED_TASK | 133 | On (no branch): orch-rescue: periodic sweep |
| `20260904T135414-5bee398fbf584c3252b3-run-18560-1788529793721372000-84b2f5b7` | CONFLICTED_NEEDS_FOCUSED_TASK | 133 | On (no branch): orch-rescue: periodic sweep |
| `20260904T140421-5bee398fbf584c3252b3-run-63755-1788530553463684000-c3e9e7fd` | CONFLICTED_NEEDS_FOCUSED_TASK | 133 | On (no branch): orch-rescue: periodic sweep |
| `20260904T143656-5bee398fbf584c3252b3-run-6773-1788532342638008000-6f2bf03e` | CONFLICTED_NEEDS_FOCUSED_TASK | 133 | On (no branch): orch-rescue: periodic sweep |
| `20260904T155649-canary-deepseek-1-35da1bce` | CONFLICTED_NEEDS_FOCUSED_TASK | 18 | On agent/canary-deepseek-1: orch-rescue: periodic sweep |
| `20260904T165711-canary-gpt-mini-3-84a96869` | CONFLICTED_NEEDS_FOCUSED_TASK | 1237 | On agent/canary-gpt-mini-3: orch-rescue: periodic sweep |
| `20260904T195545-5bee398fbf584c3252b3-e9720c04` | CONFLICTED_NEEDS_FOCUSED_TASK | 2165 | On (no branch): orch-rescue: periodic sweep |
| `20260904T204401-5bee398fbf584c3252b3-run-94466-1788554185140669000-1c036fa5` | CONFLICTED_NEEDS_FOCUSED_TASK | 2170 | On (no branch): orch-rescue: periodic sweep |
| `20260904T204953-5bee398fbf584c3252b3-run-21932-1788554649280247000-13eb52c5` | CONFLICTED_NEEDS_FOCUSED_TASK | 5133 | On (no branch): orch-rescue: periodic sweep |
| `20260904T210827-5bee398fbf584c3252b3-run-84916-1788555957293164000-340a123a` | CONFLICTED_NEEDS_FOCUSED_TASK | 2185 | On (no branch): orch-rescue: periodic sweep |
| `20260904T212139-5bee398fbf584c3252b3-run-16223-1788556487689904000-a0a39729` | CONFLICTED_NEEDS_FOCUSED_TASK | 5147 | On (no branch): orch-rescue: periodic sweep |
| `20260904T215439-canary-deepseek-1-8e66fee4` | CONFLICTED_NEEDS_FOCUSED_TASK | 18 | On agent/canary-deepseek-1: orch-rescue: periodic sweep |
| `20260905T002819-5bee398fbf584c3252b3-run-78095-1788567693256000000-86eee393` | CONFLICTED_NEEDS_FOCUSED_TASK | 2185 | On (no branch): orch-rescue: periodic sweep |
| `20260905T005818-canary-deepseek-1-e10b9d15` | CONFLICTED_NEEDS_FOCUSED_TASK | 19 | On agent/canary-deepseek-1: orch-rescue: periodic sweep |
| `20260905T010131-5bee398fbf584c3252b3-run-92737-1788569735363546000-5e594bee` | CONFLICTED_NEEDS_FOCUSED_TASK | 436 | On (no branch): orch-rescue: periodic sweep |
| `20260905T011824-5bee398fbf584c3252b3-run-34425-1788570649391996000-eb257b2b` | CONFLICTED_NEEDS_FOCUSED_TASK | 2670 | On (no branch): orch-rescue: periodic sweep |
| `20260905T021832-5bee398fbf584c3252b3-run-23135-1788574581544379000-c7c25394` | CONFLICTED_NEEDS_FOCUSED_TASK | 2720 | On (no branch): orch-rescue: periodic sweep |
| `20260905T030449-5bee398fbf584c3252b3-run-84358-1788577326191319000-0aca5f24` | CONFLICTED_NEEDS_FOCUSED_TASK | 2720 | On (no branch): orch-rescue: periodic sweep |
| `20260905T035811-5bee398fbf584c3252b3-run-61307-1788580336307846000-e10dd8ca` | CONFLICTED_NEEDS_FOCUSED_TASK | 2757 | On (no branch): orch-rescue: periodic sweep |
| `20260905T060122-canary-pin-bc8e4f53` | CONFLICTED_NEEDS_FOCUSED_TASK | 4435 | On (no branch): orch-rescue: periodic sweep |
| `20260905T063859-5bee398fbf584c3252b3-run-9092-1788589219013381000-0336b1ab` | CONFLICTED_NEEDS_FOCUSED_TASK | 2757 | On (no branch): orch-rescue: periodic sweep |
| `20260905T084737-5bee398fbf584c3252b3-run-49358-1788596941195737000-8cb4b370` | CONFLICTED_NEEDS_FOCUSED_TASK | 2757 | On (no branch): orch-rescue: periodic sweep |
| `20260905T104129-5bee398fbf584c3252b3-run-73433-1788604519262234000-59371b81` | CONFLICTED_NEEDS_FOCUSED_TASK | 2757 | On (no branch): orch-rescue: periodic sweep |
| `20260905T112144-canary-deepseek-1-0aa1329e` | CONFLICTED_NEEDS_FOCUSED_TASK | 19 | On agent/canary-deepseek-1: orch-rescue: periodic sweep |
| `20260905T121938-5bee398fbf584c3252b3-run-71553-1788609671606922000-aed6a8db` | CONFLICTED_NEEDS_FOCUSED_TASK | 2757 | On (no branch): orch-rescue: periodic sweep |
| `20260905T130608-5bee398fbf584c3252b3-run-19304-1788612760234606000-5fd0f3cd` | CONFLICTED_NEEDS_FOCUSED_TASK | 2757 | On (no branch): orch-rescue: periodic sweep |
| `20260905T135136-5bee398fbf584c3252b3-run-77119-1788616113199378000-6c2c2288` | CONFLICTED_NEEDS_FOCUSED_TASK | 2757 | On (no branch): orch-rescue: periodic sweep |
| `20260905T151013-5bee398fbf584c3252b3-run-50044-1788619697388942000-51a8599d` | CONFLICTED_NEEDS_FOCUSED_TASK | 2757 | On (no branch): orch-rescue: periodic sweep |
| `20260905T162925-5bee398fbf584c3252b3-run-11226-1788623903245992000-cd47f3bd` | CONFLICTED_NEEDS_FOCUSED_TASK | 2757 | On (no branch): orch-rescue: periodic sweep |
| `20260905T164938-5bee398fbf584c3252b3-run-82239-1788626626436122000-24fe00ed` | CONFLICTED_NEEDS_FOCUSED_TASK | 2757 | On (no branch): orch-rescue: periodic sweep |
| `20260905T174945-5bee398fbf584c3252b3-run-76204-1788630365564467000-43eed01e` | CONFLICTED_NEEDS_FOCUSED_TASK | 2757 | On (no branch): orch-rescue: periodic sweep |
| `20260905T180111-5bee398fbf584c3252b3-run-55803-1788631120786207000-2d6ded86` | CONFLICTED_NEEDS_FOCUSED_TASK | 2757 | On (no branch): orch-rescue: periodic sweep |
| `20260905T203520-5bee398fbf584c3252b3-run-97992-1788640349114282000-c3a0cd1b` | CONFLICTED_NEEDS_FOCUSED_TASK | 3126 | On (no branch): orch-rescue: periodic sweep |
| `20260906-dropped-automerge-6d74b1df` | CONFLICTED_NEEDS_FOCUSED_TASK | 8 | Merge branch 'agent/beethoven-reconcile-followup-deferred-tests-newer-module-ver |
| `20260908T002327-5bee398fbf584c3252b3-run-95881-1788824413096639000-e73b6317` | CONFLICTED_NEEDS_FOCUSED_TASK | 695 | On (no branch): orch-rescue: periodic sweep |
| `20260908T021354-5bee398fbf584c3252b3-run-66305-1788832658052891000-04360627` | CONFLICTED_NEEDS_FOCUSED_TASK | 4002 | On (no branch): orch-rescue: periodic sweep |
| `20260908T100107-improve-enhance-testing-framework-slice-5-487afb7d` | CONFLICTED_NEEDS_FOCUSED_TASK | 3 | agent: improve-enhance-testing-framework-slice-5 |
| `20260908T100126-5bee398fbf584c3252b3-run-58098-1788861542170040000-f63e7e8b` | CONFLICTED_NEEDS_FOCUSED_TASK | 3897 | On (no branch): orch-rescue: periodic sweep |
| `20260908T162028-5bee398fbf584c3252b3-run-11848-1788883528475544000-095fa7b5` | CONFLICTED_NEEDS_FOCUSED_TASK | 5591 | On (no branch): orch-rescue: periodic sweep |
| `20260909T054256-fullsuite-wt-d911a891` | CONFLICTED_NEEDS_FOCUSED_TASK | 3 | On (no branch): orch-rescue: periodic sweep |
| `20260909T054308-5bee398fbf584c3252b3-6bb0189f` | CONFLICTED_NEEDS_FOCUSED_TASK | 2167 | On (no branch): orch-rescue: periodic sweep |
| `20260909T062026-5bee398fbf584c3252b3-run-62391-1788934084200059000-1fde5d39` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | On (no branch): orch-rescue: periodic sweep |
| `20260909T065825-5bee398fbf584c3252b3-run-90679-1788936819525760000-bc8e90d6` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | On (no branch): orch-rescue: periodic sweep |
| `20260909T074105-5bee398fbf584c3252b3-run-60021-1788939519886975000-f8dedcd0` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | On (no branch): orch-rescue: periodic sweep |
| `20260909T075151-5bee398fbf584c3252b3-run-4854-1788940115440189000-7d8561b3` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | On (no branch): orch-rescue: periodic sweep |
| `20260909T080909-5bee398fbf584c3252b3-run-57416-1788941073051068000-12efe06f` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | On (no branch): orch-rescue: periodic sweep |
| `20260909T083546-5bee398fbf584c3252b3-run-5141-1788942277859007000-bc1c598a` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | On (no branch): orch-rescue: periodic sweep |
| `20260909T094229-5bee398fbf584c3252b3-run-2705-1788946476943965000-ac9f3d59` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | On (no branch): orch-rescue: periodic sweep |
| `20260909T095401-5bee398fbf584c3252b3-run-2682-1788947087542695000-24a4a615` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | On (no branch): orch-rescue: periodic sweep |
| `20260909T095402-5bee398fbf584c3252b3-run-2682-1788947514759938000-266fc6d4` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | On (no branch): orch-rescue: periodic sweep |
| `20260909T100458-5bee398fbf584c3252b3-run-39102-1788947783906985000-2cf67a76` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | On (no branch): orch-rescue: periodic sweep |
| `20260909T104359-5bee398fbf584c3252b3-run-17138-1788950452240178000-cf096bae` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | On (no branch): orch-rescue: periodic sweep |
| `20260909T122938-improve-automated-branch-management-with-gitops-slice-1-11da635f` | CONFLICTED_NEEDS_FOCUSED_TASK | 8 | task: improve-automated-branch-management-with-gitops-slice-1 |
| `20260909T122939-improve-enhance-fail-soft-error-handling-mechani-slice-4-02329da1` | CONFLICTED_NEEDS_FOCUSED_TASK | 8 | task: improve-enhance-fail-soft-error-handling-mechani-slice-4 |
| `20260909T122940-improve-enhanced-testing-infrastructure-slice-4-bbc5f606` | CONFLICTED_NEEDS_FOCUSED_TASK | 8 | task: improve-enhanced-testing-infrastructure-slice-4 |
| `20260909T122941-improve-implement-real-time-sync-between-web-and-slice-4-117a7c24` | CONFLICTED_NEEDS_FOCUSED_TASK | 8 | task: improve-implement-real-time-sync-between-web-and-slice-4 |
| `20260909T125049-5bee398fbf584c3252b3-run-16627-1788957581309763000-bdb05a5c` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | On (no branch): orch-rescue: periodic sweep |
| `20260909T132842-improve-improve-orchestration-with-ai-ml-for-dyn-slice-4-b5978208` | CONFLICTED_NEEDS_FOCUSED_TASK | 8 | task: improve-improve-orchestration-with-ai-ml-for-dyn-slice-4 |
| `20260909T133505-5bee398fbf584c3252b3-run-23929-1788960691320279000-4f8c4841` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | On (no branch): orch-rescue: periodic sweep |
| `20260909T142200-5bee398fbf584c3252b3-run-22874-1788961533327893000-bf76da41` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | On (no branch): orch-rescue: periodic sweep |
| `20260909T142656-5bee398fbf584c3252b3-run-98952-1788963756749237000-d8a9ca0c` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | On (no branch): orch-rescue: periodic sweep |
| `20260909T143247-5bee398fbf584c3252b3-run-86217-1788964277765202000-4ef92eeb` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | On (no branch): orch-rescue: periodic sweep |
| `20260909T151052-5bee398fbf584c3252b3-run-6139-1788966431398720000-82833d33` | CONFLICTED_NEEDS_FOCUSED_TASK | 10 | On (no branch): orch-rescue: periodic sweep |
| `20260909T154742-improve-automated-branch-management-with-gitops-slice-1-4cd3d60f` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | task: improve-automated-branch-management-with-gitops-slice-1 |
| `20260909T154753-improve-enhanced-testing-infrastructure-slice-4-9dc7c00d` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | task: improve-enhanced-testing-infrastructure-slice-4 |
| `20260909T154755-improve-implement-real-time-sync-between-web-and-slice-4-bd27545d` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | task: improve-implement-real-time-sync-between-web-and-slice-4 |
| `20260909T154756-improve-improve-orchestration-with-ai-ml-for-dyn-slice-4-4ba191ce` | CONFLICTED_NEEDS_FOCUSED_TASK | 9 | task: improve-improve-orchestration-with-ai-ml-for-dyn-slice-4 |
| `20260909T165556-5bee398fbf584c3252b3-run-99492-1788972183690050000-5464a5c2` | CONFLICTED_NEEDS_FOCUSED_TASK | 10 | On (no branch): orch-rescue: periodic sweep |
| `20260909T171133-improve-enhance-testing-framework-slice-5-6b55b183` | CONFLICTED_NEEDS_FOCUSED_TASK | 11 | agent: improve-enhance-testing-framework-slice-5 |
| `20260909T171250-5bee398fbf584c3252b3-run-68570-1788972997038720000-3bbaa990` | CONFLICTED_NEEDS_FOCUSED_TASK | 10 | On (no branch): orch-rescue: periodic sweep |
| `20260909T172719-5bee398fbf584c3252b3-run-52718-1788974027622641000-b571f49a` | CONFLICTED_NEEDS_FOCUSED_TASK | 10 | On (no branch): orch-rescue: periodic sweep |
| `20260909T172720-5bee398fbf584c3252b3-run-88404-1788974281017743000-5e360285` | CONFLICTED_NEEDS_FOCUSED_TASK | 10 | On (no branch): orch-rescue: periodic sweep |
| `20260909T173912-5bee398fbf584c3252b3-run-66180-1788975395379442000-5987dfe6` | CONFLICTED_NEEDS_FOCUSED_TASK | 10 | On (no branch): orch-rescue: periodic sweep |
| `20260909T173913-5bee398fbf584c3252b3-run-84412-1788974948201421000-09860a40` | CONFLICTED_NEEDS_FOCUSED_TASK | 10 | On (no branch): orch-rescue: periodic sweep |
| `20260909T175709-5bee398fbf584c3252b3-run-44623-1788975902303450000-2ea23f43` | CONFLICTED_NEEDS_FOCUSED_TASK | 10 | On (no branch): orch-rescue: periodic sweep |
| `20260909T183001-5bee398fbf584c3252b3-run-20229-1788978117199968000-701a84fe` | CONFLICTED_NEEDS_FOCUSED_TASK | 10 | On (no branch): orch-rescue: periodic sweep |
| `20260909T185251-5bee398fbf584c3252b3-run-30575-1788979862007131000-9e8681af` | CONFLICTED_NEEDS_FOCUSED_TASK | 10 | On (no branch): orch-rescue: periodic sweep |
| `20260909T185258-5bee398fbf584c3252b3-run-63399-1788978790703814000-5b450b7f` | CONFLICTED_NEEDS_FOCUSED_TASK | 10 | On (no branch): orch-rescue: periodic sweep |
| `20260909T192002-5bee398fbf584c3252b3-run-52732-1788981523627594000-066ad203` | CONFLICTED_NEEDS_FOCUSED_TASK | 10 | On (no branch): orch-rescue: periodic sweep |
| `20260909T194214-5bee398fbf584c3252b3-run-39742-1788982797607290000-fee850f7` | CONFLICTED_NEEDS_FOCUSED_TASK | 10 | On (no branch): orch-rescue: periodic sweep |
| `20260909T204938-5bee398fbf584c3252b3-run-80092-1788986771282068000-5805dcaf` | CONFLICTED_NEEDS_FOCUSED_TASK | 10 | On (no branch): orch-rescue: periodic sweep |
| `20260909T212351-5bee398fbf584c3252b3-run-14680-1788988257593359000-fa160cba` | CONFLICTED_NEEDS_FOCUSED_TASK | 10 | On (no branch): orch-rescue: periodic sweep |
| `20260909T215752-5bee398fbf584c3252b3-run-70806-1788990945165864000-196135f8` | CONFLICTED_NEEDS_FOCUSED_TASK | 10 | On (no branch): orch-rescue: periodic sweep |
| `20260909T222044-5bee398fbf584c3252b3-run-20498-1788991902823589000-5fbd281a` | CONFLICTED_NEEDS_FOCUSED_TASK | 10 | On (no branch): orch-rescue: periodic sweep |
| `20260909T222052-5bee398fbf584c3252b3-run-80905-1788992247730390000-4baaa6fc` | CONFLICTED_NEEDS_FOCUSED_TASK | 10 | On (no branch): orch-rescue: periodic sweep |
| `20260909T224415-5bee398fbf584c3252b3-run-39455-1788993701164351000-ebef9196` | CONFLICTED_NEEDS_FOCUSED_TASK | 10 | On (no branch): orch-rescue: periodic sweep |
| `20260910T000634-claude-orchestrator-b25d3fa0` | CONFLICTED_NEEDS_FOCUSED_TASK | 15 | Merge branch 'agent/chatgpt-local-reconcile-beethoven-26babe9ae13d' (auto-resolv |
| `20260910T001022-5bee398fbf584c3252b3-run-22882-1788997154962532000-20228df8` | CONFLICTED_NEEDS_FOCUSED_TASK | 10 | On (no branch): orch-rescue: periodic sweep |
| `20260910T003058-claude-orchestrator-16e4d6dd` | CONFLICTED_NEEDS_FOCUSED_TASK | 69 | Merge branch 'agent/chatgpt-local-reconcile-beethoven-f8c1bb486dd1' (auto-resolv |
| `20260910T003136-5bee398fbf584c3252b3-run-67776-1788998826259073000-76c89792` | CONFLICTED_NEEDS_FOCUSED_TASK | 26 | On (no branch): orch-rescue: periodic sweep |

## Notes

- `ACTIVE_IN_ANOTHER_TASK` items are already carried by a live `agent/*` branch; re-applying them here would duplicate queued work.
- `SUPERSEDED_BY_NEWER` is decided by commit time on the base for every source file the rescue commit touches — the newest/most complete implementation wins.
- Refs whose only content is generated (`node_modules`, `.vite`, `.nuxt`, `dist`, `coverage`, …) are classified `ALREADY_PRESENT`: a vitest cache is build noise, not lost work, and must not spawn a follow-up task that can never produce a meaningful diff.
