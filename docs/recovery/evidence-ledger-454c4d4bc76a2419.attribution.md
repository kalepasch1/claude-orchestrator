# Evidence attribution

- Audit fingerprint: `454c4d4bc76a24193c09ed80f4c8cdd76052c1854b804650a1a39f6d99d618b5`
- Attributed: 2026-08-23T19:44:21.312Z
- Items with remaining value: **403**
- Distinct tasks: **140** · unattributable: **11**

A rescue sweep fires on a timer, so one task routinely leaves many refs.
Grouping by task turns a long anonymous queue into a short list of work,
each item of which already knows what it was for.

## By attribution kind

| Kind | Items |
| --- | ---: |
| task_slug | 383 |
| run_id | 2 |
| repo_name | 0 |
| branch | 7 |
| unattributable | 11 |

## Tasks that left work behind

| Task slug | Refs | First | Last |
| --- | ---: | --- | --- |
| `claude-orchestrator` | 175 | 2026-08-03T00:07:16.000Z | 2026-08-19T20:34:33.000Z |
| `safe-edit` | 7 | 2026-08-15T17:22:19.000Z | 2026-08-17T00:05:23.000Z |
| `backlog-batch-beethoven-a86bb21-recover-pinned-exp-slice-1` | 6 | 2026-08-14T04:36:40.000Z | 2026-08-15T16:09:36.000Z |
| `pinned-express-lane` | 5 | 2026-08-06T09:38:24.000Z | 2026-08-06T22:37:37.000Z |
| `canary-gemini-25-canary-gemini-25-setup-install-dependencies` | 4 | 2026-08-15T18:08:24.000Z | 2026-08-15T20:01:10.000Z |
| `competitive-scanner-5` | 4 | 2026-08-14T03:37:35.000Z | 2026-08-14T04:06:50.000Z |
| `canary-codex-34` | 3 | 2026-08-14T04:01:29.000Z | 2026-08-14T04:18:42.000Z |
| `chatgpt-local-reconcile-beethoven-84fc83c513d9` | 3 | 2026-08-13T10:20:21.000Z | 2026-08-17T01:49:53.000Z |
| `chatgpt-local-reconcile-beethoven-8d0702cbd5aa` | 3 | 2026-08-17T01:56:01.000Z | 2026-08-17T04:45:27.000Z |
| `fix-sweeper-branch-name-truncation` | 3 | 2026-08-14T02:37:51.000Z | 2026-08-14T02:50:58.000Z |
| `improve-queue-prevent-live-runner-merge-conflicts-slice-1` | 3 | 2026-08-14T04:50:28.000Z | 2026-08-14T05:12:47.000Z |
| `merged-requires-commit-in-prod-branch-cowork-20260806` | 3 | 2026-08-06T19:28:19.000Z | 2026-08-06T19:39:30.000Z |
| `oc-autoclear-policy` | 3 | 2026-08-03T00:07:25.000Z | 2026-08-03T00:15:20.000Z |
| `orchestrator-visibility-remediation` | 3 | 2026-08-07T12:24:39.000Z | 2026-08-07T13:06:47.000Z |
| `pinned-express` | 3 | 2026-08-13T20:11:01.000Z | 2026-08-13T20:22:24.000Z |
| `relfix-racefeed-07060650-slice-4` | 3 | 2026-08-03T00:07:26.000Z | 2026-08-03T00:15:21.000Z |
| `unbounded-scan-window-class-audit-cowork-20260806` | 3 | 2026-08-06T21:44:51.000Z | 2026-08-06T21:57:26.000Z |
| `b4-lane1` | 2 | 2026-08-14T00:11:31.000Z | 2026-08-14T00:18:17.000Z |
| `backlog-batch-beethoven-22ee5bc-prompt-evolution-bandit-add-bandit-algorithm` | 2 | 2026-08-13T20:22:21.000Z | 2026-08-13T20:28:11.000Z |
| `backlog-batch-beethoven-a85e307` | 2 | 2026-08-14T02:01:57.000Z | 2026-08-14T02:09:01.000Z |
| `backlog-batch-beethoven-ad8643f` | 2 | 2026-08-06T18:45:34.000Z | 2026-08-06T18:57:50.000Z |
| `backlog-batch-beethoven-d2ada8e` | 2 | 2026-08-06T22:55:59.000Z | 2026-08-06T22:59:12.000Z |
| `backlog-batch-beethoven-d3151d8` | 2 | 2026-08-14T04:56:39.000Z | 2026-08-14T05:02:04.000Z |
| `backlog-batch-beethoven-e63dfee-apply-economic-scheduler-revenue-patch-test-and-` | 2 | 2026-08-06T06:15:14.000Z | 2026-08-06T06:22:56.000Z |
| `c27-minimal` | 2 | 2026-08-13T23:38:26.000Z | 2026-08-13T23:43:27.000Z |
| `chatgpt-local-reconcile-beethoven-6c8911116873` | 2 | 2026-08-13T06:25:15.000Z | 2026-08-13T06:31:06.000Z |
| `chatgpt-local-reconcile-beethoven-e0945946bd0d` | 2 | 2026-08-13T08:12:08.000Z | 2026-08-13T08:17:46.000Z |
| `chatgpt-local-reconcile-beethoven-fa219072749e` | 2 | 2026-08-15T23:06:09.000Z | 2026-08-15T23:11:52.000Z |
| `chatgpt-local-reconcile-beethoven-fa5a31393f8a` | 2 | 2026-08-13T05:06:45.000Z | 2026-08-13T05:15:04.000Z |
| `contracts-smarter` | 2 | 2026-08-18T10:36:48.000Z | 2026-08-18T22:37:19.000Z |
| `crashloop-cluster-049e2f00` | 2 | 2026-08-14T02:09:02.000Z | 2026-08-14T02:14:06.000Z |
| `deployfix-beethoven-07190338-fix-and-verify-vercel-production-build` | 2 | 2026-08-05T14:54:54.000Z | 2026-08-05T15:06:20.000Z |
| `dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-3-speed-triage-routing-accelerators-p0` | 2 | 2026-08-13T21:39:03.000Z | 2026-08-13T22:41:56.000Z |
| `fix-canonical-enqueue-trigger-regression-20260812` | 2 | 2026-08-13T08:47:25.000Z | 2026-08-13T08:51:37.000Z |
| `improve-missing-branch-auto-recovery-fleet-wide-slice-3-validate-repository` | 2 | 2026-08-14T00:11:33.000Z | 2026-08-14T00:18:18.000Z |
| `improve-value-aware-test-routing-early-exit-r-slice-3-adapt-merged-patterns` | 2 | 2026-08-06T10:00:04.000Z | 2026-08-06T13:10:26.000Z |
| `improve-value-aware-test-routing-early-exit-r-slice-3-fix-broken-tests` | 2 | 2026-08-06T20:18:09.000Z | 2026-08-06T20:26:15.000Z |
| `orchestrator-session-fabric-current` | 2 | 2026-08-11T15:25:27.000Z | 2026-08-13T03:44:49.000Z |
| `pareto-regime` | 2 | 2026-08-13T04:01:44.000Z | 2026-08-13T04:07:06.000Z |
| `perpetual-compliance-hedge-instrument-fix-ts-errors-and-run-tests-fix-typescript` | 2 | 2026-08-06T09:12:53.000Z | 2026-08-06T09:15:47.000Z |
| `release-on-capacity-not-clock-cowork-20260806` | 2 | 2026-08-06T19:44:27.000Z | 2026-08-17T03:58:48.000Z |
| `subscription-tier-monitor` | 2 | 2026-08-15T15:13:39.000Z | 2026-08-15T15:19:39.000Z |
| `wt-fix1` | 2 | 2026-08-19T12:57:13.000Z | 2026-08-19T13:02:11.000Z |
| `_fix_rc` | 1 | 2026-08-13T08:57:54.000Z | 2026-08-13T08:57:54.000Z |
| `auto-resolve-must-not-silently-discard-cowork-20260806` | 1 | 2026-08-06T21:34:35.000Z | 2026-08-06T21:34:35.000Z |
| `backlog-batch-apparently-0d157dd-fix-render-decision-briefs-review` | 1 | 2026-08-05T21:39:02.000Z | 2026-08-05T21:39:02.000Z |
| `backlog-batch-beethoven-18fa8e4-slice-1` | 1 | 2026-08-06T23:41:45.000Z | 2026-08-06T23:41:45.000Z |
| `backlog-batch-beethoven-22ee5bc-convention-conform-slice-2-8309febb` | 1 | 2026-08-13T23:19:31.000Z | 2026-08-13T23:19:31.000Z |
| `backlog-batch-beethoven-22ee5bc-prompt-evolution-bandit-update-claude-interface-67280171` | 1 | 2026-08-13T23:19:32.000Z | 2026-08-13T23:19:32.000Z |
| `backlog-batch-beethoven-22ee5bc-recover-pinned-express-lane-add-tests-and-verify` | 1 | 2026-08-06T23:09:31.000Z | 2026-08-06T23:09:31.000Z |
| `backlog-batch-beethoven-22ee5bc-rework-pinned-express-lane` | 1 | 2026-08-06T19:09:13.000Z | 2026-08-06T19:09:13.000Z |
| `backlog-batch-beethoven-288ebe8` | 1 | 2026-08-14T00:31:41.000Z | 2026-08-14T00:31:41.000Z |
| `backlog-batch-beethoven-97e0e39-optimize-prompt-evolution` | 1 | 2026-08-06T20:59:01.000Z | 2026-08-06T20:59:01.000Z |
| `backlog-batch-beethoven-d00ef24-prompt-evolution-bandit-verify-build` | 1 | 2026-08-06T22:32:21.000Z | 2026-08-06T22:32:21.000Z |
| `canary-claude-27-slice-1-run-checks` | 1 | 2026-08-14T00:18:18.000Z | 2026-08-14T00:18:18.000Z |
| `canary-claude-27-slice-3-adapt-prior-merged-patterns-extract-proven-diffs-docume` | 1 | 2026-08-13T09:12:06.000Z | 2026-08-13T09:12:06.000Z |
| `canary-claude-27-slice-3-adapt-prior-merged-patterns-extract-proven-diffs-extrac-15227eb7` | 1 | 2026-08-13T23:19:32.000Z | 2026-08-13T23:19:32.000Z |
| `canary-codex-34-retry-fix` | 1 | 2026-08-14T01:50:51.000Z | 2026-08-14T01:50:51.000Z |
| `canary-gemini-25-canary-gemini-25-setup-add-basic-main-function-setup-import-req` | 1 | 2026-08-06T10:00:01.000Z | 2026-08-06T10:00:01.000Z |
| `chatgpt-local-queue-pr20` | 1 | 2026-08-11T16:20:01.000Z | 2026-08-11T16:20:01.000Z |
| `chatgpt-local-reconcile-beethoven-10d6c3591091` | 1 | 2026-08-13T06:14:43.000Z | 2026-08-13T06:14:43.000Z |
| `chatgpt-local-reconcile-beethoven-215fba971ab9` | 1 | 2026-08-13T07:26:04.000Z | 2026-08-13T07:26:04.000Z |
| `chatgpt-local-reconcile-beethoven-383306e1301e` | 1 | 2026-08-13T08:37:37.000Z | 2026-08-13T08:37:37.000Z |
| `chatgpt-local-reconcile-beethoven-3b50d1e569de` | 1 | 2026-08-13T09:12:06.000Z | 2026-08-13T09:12:06.000Z |
| `chatgpt-local-reconcile-beethoven-4d83819ff744` | 1 | 2026-08-13T07:26:05.000Z | 2026-08-13T07:26:05.000Z |
| `chatgpt-local-reconcile-beethoven-55acd60c79b1` | 1 | 2026-08-17T01:02:32.000Z | 2026-08-17T01:02:32.000Z |
| `chatgpt-local-reconcile-beethoven-5e30d0e05126` | 1 | 2026-08-13T10:20:21.000Z | 2026-08-13T10:20:21.000Z |
| `chatgpt-local-reconcile-beethoven-671c267eedf3` | 1 | 2026-08-17T02:01:54.000Z | 2026-08-17T02:01:54.000Z |
| `chatgpt-local-reconcile-beethoven-797668765dad` | 1 | 2026-08-13T07:26:05.000Z | 2026-08-13T07:26:05.000Z |
| `chatgpt-local-reconcile-beethoven-7b6f925e1e7a` | 1 | 2026-08-17T02:08:32.000Z | 2026-08-17T02:08:32.000Z |
| `chatgpt-local-reconcile-beethoven-85d2de799d5d` | 1 | 2026-08-17T03:53:01.000Z | 2026-08-17T03:53:01.000Z |
| `chatgpt-local-reconcile-beethoven-ac93979d6c7a` | 1 | 2026-08-13T08:00:48.000Z | 2026-08-13T08:00:48.000Z |
| `chatgpt-local-reconcile-beethoven-ca93a1b7be55` | 1 | 2026-08-17T02:08:36.000Z | 2026-08-17T02:08:36.000Z |
| `chatgpt-local-reconcile-beethoven-e4b9212494ba` | 1 | 2026-08-13T07:02:24.000Z | 2026-08-13T07:02:24.000Z |
| `crashloop-387dfa7` | 1 | 2026-08-06T23:15:18.000Z | 2026-08-06T23:15:18.000Z |
| `crashloop-credresolver` | 1 | 2026-08-14T01:00:41.000Z | 2026-08-14T01:00:41.000Z |
| `crashloop-integration-sweeper-cae1d4c9` | 1 | 2026-08-14T01:38:45.000Z | 2026-08-14T01:38:45.000Z |
| `done-before-card-is-the-stranding-bug-cowork-20260806` | 1 | 2026-08-06T21:30:05.000Z | 2026-08-06T21:30:05.000Z |
| `dropbox-beethoven-audit-addendum-group-4` | 1 | 2026-08-06T19:54:48.000Z | 2026-08-06T19:54:48.000Z |
| `dropbox-beethoven-audit-addendum-two-session-recon-slice-1` | 1 | 2026-08-06T10:37:18.000Z | 2026-08-06T10:37:18.000Z |
| `dropbox-beethoven-audit-addendum-two-session-recon-slice-5` | 1 | 2026-08-13T06:25:16.000Z | 2026-08-13T06:25:16.000Z |
| `dropbox-beethoven-audit-addendum-two-session-reconciliation-read-wit-group-1` | 1 | 2026-08-05T18:30:28.000Z | 2026-08-05T18:30:28.000Z |
| `dropbox-beethoven-audit-addendum-two-session-reconciliation-read-wit-group-5` | 1 | 2026-08-13T20:52:13.000Z | 2026-08-13T20:52:13.000Z |
| `dropbox-beethoven-fleet-immune-system-1` | 1 | 2026-08-14T03:07:59.000Z | 2026-08-14T03:07:59.000Z |
| `dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-2-machine-pipeline-heartbeat-alerts-p0-recovered` | 1 | 2026-08-06T17:46:24.000Z | 2026-08-06T17:46:24.000Z |
| `dropbox-hisanta-mastery-engine-grandma-rail-family-slice-1` | 1 | 2026-08-06T16:29:55.000Z | 2026-08-06T16:29:55.000Z |
| `dropbox-hisanta-mastery-engine-grandma-rail-family-slice-2` | 1 | 2026-08-06T18:12:45.000Z | 2026-08-06T18:12:45.000Z |
| `dropbox-hisanta-mastery-engine-grandma-rail-family-slice-3` | 1 | 2026-08-06T16:29:55.000Z | 2026-08-06T16:29:55.000Z |
| `dropbox-mission-complete-batch-fusion-unpause` | 1 | 2026-08-06T18:18:33.000Z | 2026-08-06T18:18:33.000Z |
| `dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-batch-fusion-unpause` | 1 | 2026-08-15T20:10:40.000Z | 2026-08-15T20:10:40.000Z |
| `dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-governor-ram-floor` | 1 | 2026-08-06T15:34:23.000Z | 2026-08-06T15:34:23.000Z |
| `dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-keepalive-single-supervisor` | 1 | 2026-08-06T16:49:30.000Z | 2026-08-06T16:49:30.000Z |
| `dropbox-operator-gate-amendment-auto-ship-authoriz-slice-2` | 1 | 2026-08-06T17:27:35.000Z | 2026-08-06T17:27:35.000Z |
| `dropbox-recover-lease-night-g1` | 1 | 2026-08-14T04:50:28.000Z | 2026-08-14T04:50:28.000Z |
| `ensemble-on-hard` | 1 | 2026-08-04T18:19:13.000Z | 2026-08-04T18:19:13.000Z |
| `fix-compilation-types` | 1 | 2026-08-06T22:15:12.000Z | 2026-08-06T22:15:12.000Z |
| `fix-core-rpc-retry` | 1 | 2026-08-15T16:32:23.000Z | 2026-08-15T16:32:23.000Z |
| `fleet-immune-1` | 1 | 2026-08-14T03:20:24.000Z | 2026-08-14T03:20:24.000Z |
| `fleet-immune-p0` | 1 | 2026-08-05T18:46:58.000Z | 2026-08-05T18:46:58.000Z |
| `immune-p0` | 1 | 2026-08-17T05:50:34.000Z | 2026-08-17T05:50:34.000Z |
| `improve-automate-branch-management-slice-3` | 1 | 2026-08-07T22:05:46.000Z | 2026-08-07T22:05:46.000Z |
| `improve-implement-real-time-sync-with-supabase-slice-1` | 1 | 2026-08-04T05:17:46.000Z | 2026-08-04T05:17:46.000Z |
| `improve-missing-branch-auto-creator-slice-3-adapt-auto-branch-patch` | 1 | 2026-08-06T10:00:03.000Z | 2026-08-06T10:00:03.000Z |
| `improve-missing-branch-auto-creator-slice-3-locate-decomposition-event-handler-a` | 1 | 2026-08-06T10:00:03.000Z | 2026-08-06T10:00:03.000Z |
| `improve-upgrade-to-a-high-performance-database-slice-3-integrate-new-module` | 1 | 2026-08-06T22:42:41.000Z | 2026-08-06T22:42:41.000Z |
| `is-merge-commit` | 1 | 2026-08-06T23:53:17.000Z | 2026-08-06T23:53:17.000Z |
| `leasenight` | 1 | 2026-08-14T07:27:12.000Z | 2026-08-14T07:27:12.000Z |
| `low-ev-early-exit` | 1 | 2026-08-07T00:17:58.000Z | 2026-08-07T00:17:58.000Z |
| `p4-household` | 1 | 2026-08-17T05:50:35.000Z | 2026-08-17T05:50:35.000Z |
| `phantom` | 1 | 2026-08-14T08:07:19.000Z | 2026-08-14T08:07:19.000Z |
| `pinned-exp` | 1 | 2026-08-06T18:57:59.000Z | 2026-08-06T18:57:59.000Z |
| `promotion-window` | 1 | 2026-08-06T23:24:44.000Z | 2026-08-06T23:24:44.000Z |
| `qafix-beethoven-07230101` | 1 | 2026-08-04T16:50:21.000Z | 2026-08-04T16:50:21.000Z |
| `reconcile-beethoven-55acd60c` | 1 | 2026-08-13T04:53:20.000Z | 2026-08-13T04:53:20.000Z |
| `reconcile-wt` | 1 | 2026-08-19T01:37:53.000Z | 2026-08-19T01:37:53.000Z |
| `recover-unregistered-repo-trojun-orchestrator-misclone` | 1 | 2026-08-15T11:51:59.000Z | 2026-08-15T11:51:59.000Z |
| `regen-improve-enhance-automated-testing-and-integratio-slice-5` | 1 | 2026-08-18T12:21:51.000Z | 2026-08-18T12:21:51.000Z |
| `regen-improve-enhance-testing-framework-slice-5` | 1 | 2026-08-18T12:22:08.000Z | 2026-08-18T12:22:08.000Z |
| `regen-recover-missing-branch-backlog-blitz-context-diet-verify` | 1 | 2026-08-18T12:22:14.000Z | 2026-08-18T12:22:14.000Z |
| `release-push-must-fast-forward-cowork-20260806` | 1 | 2026-08-06T19:39:31.000Z | 2026-08-06T19:39:31.000Z |
| `relfix-release-hold-deadlock-cowork-20260806` | 1 | 2026-08-06T16:11:11.000Z | 2026-08-06T16:11:11.000Z |
| `relfix-vercel-checks-cache-verify-relfix-vercel-checks-cache` | 1 | 2026-08-06T09:33:10.000Z | 2026-08-06T09:33:10.000Z |
| `remediate-dropbox-wave-c-compounding-codegen-platform-spine--ca8794` | 1 | 2026-08-14T02:44:38.000Z | 2026-08-14T02:44:38.000Z |
| `rework-legal-recover-missing-branch-improve-enhanced-testing-pipeline-re-20484dc` | 1 | 2026-08-04T14:55:36.000Z | 2026-08-04T14:55:36.000Z |
| `rework-secret-a2a-endpoint-0743615` | 1 | 2026-08-18T12:51:28.000Z | 2026-08-18T12:51:28.000Z |
| `rt-sync` | 1 | 2026-08-06T22:37:41.000Z | 2026-08-06T22:37:41.000Z |
| `session-proof-of-work` | 1 | 2026-08-18T20:32:12.000Z | 2026-08-18T20:32:12.000Z |
| `smarter-5-95` | 1 | 2026-08-18T12:22:20.000Z | 2026-08-18T12:22:20.000Z |
| `stale-backlog-456` | 1 | 2026-08-06T23:07:45.000Z | 2026-08-06T23:07:45.000Z |
| `stub-recover-missing-branch-backlog-blitz-context-diet-verify` | 1 | 2026-08-18T12:22:38.000Z | 2026-08-18T12:22:38.000Z |
| `sweeper-rederive` | 1 | 2026-08-18T00:08:34.000Z | 2026-08-18T00:08:34.000Z |
| `testcmd` | 1 | 2026-08-07T00:12:24.000Z | 2026-08-07T00:12:24.000Z |
| `verify-immune` | 1 | 2026-08-06T20:52:58.000Z | 2026-08-06T20:52:58.000Z |
| `wavec-p4` | 1 | 2026-08-14T07:27:17.000Z | 2026-08-14T07:27:17.000Z |
| `wire-merge-detection` | 1 | 2026-08-06T23:55:43.000Z | 2026-08-06T23:55:43.000Z |
| `wt-canary` | 1 | 2026-08-19T01:07:08.000Z | 2026-08-19T01:07:08.000Z |
| `wt-fix2` | 1 | 2026-08-19T13:08:33.000Z | 2026-08-19T13:08:33.000Z |
| `wt-fix3` | 1 | 2026-08-19T13:21:17.000Z | 2026-08-19T13:21:17.000Z |
| `wt-inert` | 1 | 2026-08-19T01:33:45.000Z | 2026-08-19T01:33:45.000Z |
| `wt-origin` | 1 | 2026-08-19T00:37:23.000Z | 2026-08-19T00:37:23.000Z |

Before opening a follow-up for any of these, check whether the task is still
live. If it is, letting it finish beats opening a second one.
