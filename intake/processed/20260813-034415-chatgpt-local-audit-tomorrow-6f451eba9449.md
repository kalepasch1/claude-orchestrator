PROJECT: tomorrow

- id: chatgpt-local-reconcile-tomorrow-6f451eba9449
  title: Reconcile local ChatGPT/Codex build evidence for tomorrow
  material: yes
  depends: []
  proof: every evidence item is classified and all still-useful absent code is durably queued or integrated
  prompt: |
    Reconcile the local ChatGPT/Codex build evidence below without destroying or overwriting it.

    This is a recovery-and-consideration task, not permission to prefer legacy code over current code.
    Treat every source path, stash, rescue ref, and worktree as read-only. Compare each item against
    the current default branch, remote branches, merged history, and live orchestrator tasks. Classify
    each item as ALREADY_PRESENT, SUPERSEDED_BY_NEWER, ACTIVE_IN_ANOTHER_TASK, RECOVERABLE_VALUE, or
    CONFLICTED_NEEDS_FOCUSED_TASK. The newest/most complete implementation wins.

    For RECOVERABLE_VALUE, work only in a newly allocated isolated worktree, apply the minimum coherent
    diff, run relevant tests, and deliver through the normal agent branch + merge train. For conflicts,
    queue a focused follow-up rather than forcing an overwrite. Do not delete, reset, clean, pop, or move
    the evidence source. Do not duplicate work already represented by a live task or remote branch.

    Write one `coordination_tasks` recovery-ledger record per evidence item using audit fingerprint
    `6f451eba94491e8e38262d60c74bfcf5214d5334f34c7e5b68b8fa3580bc6e2f`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "agent/recover-missing-branch-perpetual-compliance-hedge-instrument-fix-ts-errors-and-run-tests-inspect-and-re",
        "change_count": 1,
        "changes": [
          "packages/curation-core/node_modules/.vite/vitest/da39a3ee5e6b4b0d3255bfef95601890afd80709/results.json"
        ],
        "changes_digest": "57f90ec4d4c0896116a6af3cb2ad565771de743f6f1f96c35b413e7db8bbe304",
        "head": "25b496a41bc64d403fd6e397331e97c50c7ecb29",
        "kind": "dirty_worktree",
        "newest_change_mtime": 0,
        "path": "/Users/kpasch/Documents/beethoven/claude-orchestrator/.runtime/integration-worktrees/6973da69fb225e176b92"
      },
      {
        "branch": "agent/cx-determination-slo",
        "change_count": 199,
        "changes_digest": "c50eeddc98b68f280f8a838d12d9945216c46adbd83b7c9aed73619f15d975de",
        "changes_sample": [
          ".deploy-canary",
          ".husky/pre-commit",
          ".recovery-intent-adversarial-second-opinion-split-the-build-task-in-slice-5-match-prior-artifact.txt",
          ".recovery-intent-backlog-batch-tomorrow-4210042.txt",
          ".recovery-intent-backlog-batch-tomorrow-c44138a.txt",
          ".recovery-intent-backlog-batch-tomorrow-d8f0b3a.txt",
          ".recovery-intent-cont-97381e.txt",
          ".recovery-intent-curation-snapshot-diff-alerts.txt",
          ".recovery-intent-dropbox-economic-scheduler-revenue-revenue-focused-task-prioritizati-group-1-upd.txt",
          ".recovery-intent-dropbox-economic-scheduler-revenue-revenue-focused-task-prioritizati-group-4-imp.txt",
          ".recovery-intent-dropbox-economic-scheduler-revenue-revenue-focused-task-prioritizati-group-5-imp.txt",
          ".recovery-intent-dropbox-pareto-2080-luxury-consigliere-repositioning-5m-ecp-passport-master-task.txt",
          ".recovery-intent-qafix-tomorrow-07062319-slice-4-slice-4-implement-core-adapted-logic-patch-templ.txt",
          ".recovery-intent-recover-missing-branch-determinations-engine-spec-slice-2.txt",
          ".recovery-intent-recover-missing-branch-merge-legacy-fix-vue-css.txt",
          ".recovery-intent-recover-missing-branch-perpetual-compliance-hedge-instrument-restore-npm-deps.txt",
          ".recovery-intent-recover-missing-branch-sik-verification.txt",
          ".recovery-intent-remediate-qafix-tomorrow-07062319-slice-1-slice-5-locateexistingownermodulefunct.txt",
          ".recovery-intent-remediate-spec-reconcile-3fb58a.txt",
          ".tsc-error-baseline",
          "AUTH_NOTES.md",
          "BACKLOG-BATCH-7CE8BFB.md",
          "COMPLETENESS_CREDIT_50X_OPPORTUNITIES.md",
          "COMPLETENESS_CREDIT_LAUNCH_REMEDIATIONS.md",
          "ECP_CADE_REVISED_OUTLINE_2026-07-13.md",
          "IMPLEMENTATION_COMPLETE.md",
          "IMPLEMENTATION_SUMMARY.md",
          "INTELLIGENCE_SELF_ASSESSMENT_2026-07-24.md",
          "PLATFORM_ACCELERATION_REVIEW.md",
          "REWORK-LEGAL-QAFIX-SLICE-4-TRANSPLANT-9D414CE.md"
        ],
        "changes_total": 100,
        "head": "b431cb921b633fcd939ea82d47c5c47926ede3a2",
        "kind": "dirty_worktree",
        "newest_change_mtime": 0,
        "path": "/Users/kpasch/Documents/tomorrow/tomorrow-wt/cx-determination-slo"
      },
      {
        "branch": "agent/cx-shadow-cade",
        "change_count": 199,
        "changes_digest": "c50eeddc98b68f280f8a838d12d9945216c46adbd83b7c9aed73619f15d975de",
        "changes_sample": [
          ".deploy-canary",
          ".husky/pre-commit",
          ".recovery-intent-adversarial-second-opinion-split-the-build-task-in-slice-5-match-prior-artifact.txt",
          ".recovery-intent-backlog-batch-tomorrow-4210042.txt",
          ".recovery-intent-backlog-batch-tomorrow-c44138a.txt",
          ".recovery-intent-backlog-batch-tomorrow-d8f0b3a.txt",
          ".recovery-intent-cont-97381e.txt",
          ".recovery-intent-curation-snapshot-diff-alerts.txt",
          ".recovery-intent-dropbox-economic-scheduler-revenue-revenue-focused-task-prioritizati-group-1-upd.txt",
          ".recovery-intent-dropbox-economic-scheduler-revenue-revenue-focused-task-prioritizati-group-4-imp.txt",
          ".recovery-intent-dropbox-economic-scheduler-revenue-revenue-focused-task-prioritizati-group-5-imp.txt",
          ".recovery-intent-dropbox-pareto-2080-luxury-consigliere-repositioning-5m-ecp-passport-master-task.txt",
          ".recovery-intent-qafix-tomorrow-07062319-slice-4-slice-4-implement-core-adapted-logic-patch-templ.txt",
          ".recovery-intent-recover-missing-branch-determinations-engine-spec-slice-2.txt",
          ".recovery-intent-recover-missing-branch-merge-legacy-fix-vue-css.txt",
          ".recovery-intent-recover-missing-branch-perpetual-compliance-hedge-instrument-restore-npm-deps.txt",
          ".recovery-intent-recover-missing-branch-sik-verification.txt",
          ".recovery-intent-remediate-qafix-tomorrow-07062319-slice-1-slice-5-locateexistingownermodulefunct.txt",
          ".recovery-intent-remediate-spec-reconcile-3fb58a.txt",
          ".tsc-error-baseline",
          "AUTH_NOTES.md",
          "BACKLOG-BATCH-7CE8BFB.md",
          "COMPLETENESS_CREDIT_50X_OPPORTUNITIES.md",
          "COMPLETENESS_CREDIT_LAUNCH_REMEDIATIONS.md",
          "ECP_CADE_REVISED_OUTLINE_2026-07-13.md",
          "IMPLEMENTATION_COMPLETE.md",
          "IMPLEMENTATION_SUMMARY.md",
          "INTELLIGENCE_SELF_ASSESSMENT_2026-07-24.md",
          "PLATFORM_ACCELERATION_REVIEW.md",
          "REWORK-LEGAL-QAFIX-SLICE-4-TRANSPLANT-9D414CE.md"
        ],
        "changes_total": 100,
        "head": "b431cb921b633fcd939ea82d47c5c47926ede3a2",
        "kind": "dirty_worktree",
        "newest_change_mtime": 0,
        "path": "/Users/kpasch/Documents/tomorrow/tomorrow-wt/cx-shadow-cade"
      },
      {
        "branch": "agent/deploy-journey-verification",
        "change_count": 199,
        "changes_digest": "c50eeddc98b68f280f8a838d12d9945216c46adbd83b7c9aed73619f15d975de",
        "changes_sample": [
          ".deploy-canary",
          ".husky/pre-commit",
          ".recovery-intent-adversarial-second-opinion-split-the-build-task-in-slice-5-match-prior-artifact.txt",
          ".recovery-intent-backlog-batch-tomorrow-4210042.txt",
          ".recovery-intent-backlog-batch-tomorrow-c44138a.txt",
          ".recovery-intent-backlog-batch-tomorrow-d8f0b3a.txt",
          ".recovery-intent-cont-97381e.txt",
          ".recovery-intent-curation-snapshot-diff-alerts.txt",
          ".recovery-intent-dropbox-economic-scheduler-revenue-revenue-focused-task-prioritizati-group-1-upd.txt",
          ".recovery-intent-dropbox-economic-scheduler-revenue-revenue-focused-task-prioritizati-group-4-imp.txt",
          ".recovery-intent-dropbox-economic-scheduler-revenue-revenue-focused-task-prioritizati-group-5-imp.txt",
          ".recovery-intent-dropbox-pareto-2080-luxury-consigliere-repositioning-5m-ecp-passport-master-task.txt",
          ".recovery-intent-qafix-tomorrow-07062319-slice-4-slice-4-implement-core-adapted-logic-patch-templ.txt",
          ".recovery-intent-recover-missing-branch-determinations-engine-spec-slice-2.txt",
          ".recovery-intent-recover-missing-branch-merge-legacy-fix-vue-css.txt",
          ".recovery-intent-recover-missing-branch-perpetual-compliance-hedge-instrument-restore-npm-deps.txt",
          ".recovery-intent-recover-missing-branch-sik-verification.txt",
          ".recovery-intent-remediate-qafix-tomorrow-07062319-slice-1-slice-5-locateexistingownermodulefunct.txt",
          ".recovery-intent-remediate-spec-reconcile-3fb58a.txt",
          ".tsc-error-baseline",
          "AUTH_NOTES.md",
          "BACKLOG-BATCH-7CE8BFB.md",
          "COMPLETENESS_CREDIT_50X_OPPORTUNITIES.md",
          "COMPLETENESS_CREDIT_LAUNCH_REMEDIATIONS.md",
          "ECP_CADE_REVISED_OUTLINE_2026-07-13.md",
          "IMPLEMENTATION_COMPLETE.md",
          "IMPLEMENTATION_SUMMARY.md",
          "INTELLIGENCE_SELF_ASSESSMENT_2026-07-24.md",
          "PLATFORM_ACCELERATION_REVIEW.md",
          "REWORK-LEGAL-QAFIX-SLICE-4-TRANSPLANT-9D414CE.md"
        ],
        "changes_total": 100,
        "head": "b431cb921b633fcd939ea82d47c5c47926ede3a2",
        "kind": "dirty_worktree",
        "newest_change_mtime": 0,
        "path": "/Users/kpasch/Documents/tomorrow/tomorrow-wt/deploy-journey-verification"
      },
      {
        "branch": "agent/orch-cross-project-depends",
        "change_count": 199,
        "changes_digest": "c50eeddc98b68f280f8a838d12d9945216c46adbd83b7c9aed73619f15d975de",
        "changes_sample": [
          ".deploy-canary",
          ".husky/pre-commit",
          ".recovery-intent-adversarial-second-opinion-split-the-build-task-in-slice-5-match-prior-artifact.txt",
          ".recovery-intent-backlog-batch-tomorrow-4210042.txt",
          ".recovery-intent-backlog-batch-tomorrow-c44138a.txt",
          ".recovery-intent-backlog-batch-tomorrow-d8f0b3a.txt",
          ".recovery-intent-cont-97381e.txt",
          ".recovery-intent-curation-snapshot-diff-alerts.txt",
          ".recovery-intent-dropbox-economic-scheduler-revenue-revenue-focused-task-prioritizati-group-1-upd.txt",
          ".recovery-intent-dropbox-economic-scheduler-revenue-revenue-focused-task-prioritizati-group-4-imp.txt",
          ".recovery-intent-dropbox-economic-scheduler-revenue-revenue-focused-task-prioritizati-group-5-imp.txt",
          ".recovery-intent-dropbox-pareto-2080-luxury-consigliere-repositioning-5m-ecp-passport-master-task.txt",
          ".recovery-intent-qafix-tomorrow-07062319-slice-4-slice-4-implement-core-adapted-logic-patch-templ.txt",
          ".recovery-intent-recover-missing-branch-determinations-engine-spec-slice-2.txt",
          ".recovery-intent-recover-missing-branch-merge-legacy-fix-vue-css.txt",
          ".recovery-intent-recover-missing-branch-perpetual-compliance-hedge-instrument-restore-npm-deps.txt",
          ".recovery-intent-recover-missing-branch-sik-verification.txt",
          ".recovery-intent-remediate-qafix-tomorrow-07062319-slice-1-slice-5-locateexistingownermodulefunct.txt",
          ".recovery-intent-remediate-spec-reconcile-3fb58a.txt",
          ".tsc-error-baseline",
          "AUTH_NOTES.md",
          "BACKLOG-BATCH-7CE8BFB.md",
          "COMPLETENESS_CREDIT_50X_OPPORTUNITIES.md",
          "COMPLETENESS_CREDIT_LAUNCH_REMEDIATIONS.md",
          "ECP_CADE_REVISED_OUTLINE_2026-07-13.md",
          "IMPLEMENTATION_COMPLETE.md",
          "IMPLEMENTATION_SUMMARY.md",
          "INTELLIGENCE_SELF_ASSESSMENT_2026-07-24.md",
          "PLATFORM_ACCELERATION_REVIEW.md",
          "REWORK-LEGAL-QAFIX-SLICE-4-TRANSPLANT-9D414CE.md"
        ],
        "changes_total": 100,
        "head": "4e1184e5374e3be140da1cb7512d8b7bc52edf7d",
        "kind": "dirty_worktree",
        "newest_change_mtime": 0,
        "path": "/Users/kpasch/Documents/tomorrow/tomorrow-wt/orch-cross-project-depends"
      },
      {
        "branch": "agent/rework-oversized-relfix-racefeed-07060650-sub-task-4-report-failure-if-n-5cfe75f",
        "change_count": 199,
        "changes_digest": "c50eeddc98b68f280f8a838d12d9945216c46adbd83b7c9aed73619f15d975de",
        "changes_sample": [
          ".deploy-canary",
          ".husky/pre-commit",
          ".recovery-intent-adversarial-second-opinion-split-the-build-task-in-slice-5-match-prior-artifact.txt",
          ".recovery-intent-backlog-batch-tomorrow-4210042.txt",
          ".recovery-intent-backlog-batch-tomorrow-c44138a.txt",
          ".recovery-intent-backlog-batch-tomorrow-d8f0b3a.txt",
          ".recovery-intent-cont-97381e.txt",
          ".recovery-intent-curation-snapshot-diff-alerts.txt",
          ".recovery-intent-dropbox-economic-scheduler-revenue-revenue-focused-task-prioritizati-group-1-upd.txt",
          ".recovery-intent-dropbox-economic-scheduler-revenue-revenue-focused-task-prioritizati-group-4-imp.txt",
          ".recovery-intent-dropbox-economic-scheduler-revenue-revenue-focused-task-prioritizati-group-5-imp.txt",
          ".recovery-intent-dropbox-pareto-2080-luxury-consigliere-repositioning-5m-ecp-passport-master-task.txt",
          ".recovery-intent-qafix-tomorrow-07062319-slice-4-slice-4-implement-core-adapted-logic-patch-templ.txt",
          ".recovery-intent-recover-missing-branch-determinations-engine-spec-slice-2.txt",
          ".recovery-intent-recover-missing-branch-merge-legacy-fix-vue-css.txt",
          ".recovery-intent-recover-missing-branch-perpetual-compliance-hedge-instrument-restore-npm-deps.txt",
          ".recovery-intent-recover-missing-branch-sik-verification.txt",
          ".recovery-intent-remediate-qafix-tomorrow-07062319-slice-1-slice-5-locateexistingownermodulefunct.txt",
          ".recovery-intent-remediate-spec-reconcile-3fb58a.txt",
          ".tsc-error-baseline",
          "AUTH_NOTES.md",
          "BACKLOG-BATCH-7CE8BFB.md",
          "COMPLETENESS_CREDIT_50X_OPPORTUNITIES.md",
          "COMPLETENESS_CREDIT_LAUNCH_REMEDIATIONS.md",
          "ECP_CADE_REVISED_OUTLINE_2026-07-13.md",
          "IMPLEMENTATION_COMPLETE.md",
          "IMPLEMENTATION_SUMMARY.md",
          "INTELLIGENCE_SELF_ASSESSMENT_2026-07-24.md",
          "PLATFORM_ACCELERATION_REVIEW.md",
          "REWORK-LEGAL-QAFIX-SLICE-4-TRANSPLANT-9D414CE.md"
        ],
        "changes_total": 100,
        "head": "36377051b009dd06e711914c9b71eab03434ba5e",
        "kind": "dirty_worktree",
        "newest_change_mtime": 0,
        "path": "/Users/kpasch/Documents/tomorrow/tomorrow-wt/rework-oversized-relfix-racefeed-07060650-sub-task-4-report-failure-if-n-5cfe75f"
      },
      {
        "branch": "agent/session-proof-of-work",
        "change_count": 199,
        "changes_digest": "c50eeddc98b68f280f8a838d12d9945216c46adbd83b7c9aed73619f15d975de",
        "changes_sample": [
          ".deploy-canary",
          ".husky/pre-commit",
          ".recovery-intent-adversarial-second-opinion-split-the-build-task-in-slice-5-match-prior-artifact.txt",
          ".recovery-intent-backlog-batch-tomorrow-4210042.txt",
          ".recovery-intent-backlog-batch-tomorrow-c44138a.txt",
          ".recovery-intent-backlog-batch-tomorrow-d8f0b3a.txt",
          ".recovery-intent-cont-97381e.txt",
          ".recovery-intent-curation-snapshot-diff-alerts.txt",
          ".recovery-intent-dropbox-economic-scheduler-revenue-revenue-focused-task-prioritizati-group-1-upd.txt",
          ".recovery-intent-dropbox-economic-scheduler-revenue-revenue-focused-task-prioritizati-group-4-imp.txt",
          ".recovery-intent-dropbox-economic-scheduler-revenue-revenue-focused-task-prioritizati-group-5-imp.txt",
          ".recovery-intent-dropbox-pareto-2080-luxury-consigliere-repositioning-5m-ecp-passport-master-task.txt",
          ".recovery-intent-qafix-tomorrow-07062319-slice-4-slice-4-implement-core-adapted-logic-patch-templ.txt",
          ".recovery-intent-recover-missing-branch-determinations-engine-spec-slice-2.txt",
          ".recovery-intent-recover-missing-branch-merge-legacy-fix-vue-css.txt",
          ".recovery-intent-recover-missing-branch-perpetual-compliance-hedge-instrument-restore-npm-deps.txt",
          ".recovery-intent-recover-missing-branch-sik-verification.txt",
          ".recovery-intent-remediate-qafix-tomorrow-07062319-slice-1-slice-5-locateexistingownermodulefunct.txt",
          ".recovery-intent-remediate-spec-reconcile-3fb58a.txt",
          ".tsc-error-baseline",
          "AUTH_NOTES.md",
          "BACKLOG-BATCH-7CE8BFB.md",
          "COMPLETENESS_CREDIT_50X_OPPORTUNITIES.md",
          "COMPLETENESS_CREDIT_LAUNCH_REMEDIATIONS.md",
          "ECP_CADE_REVISED_OUTLINE_2026-07-13.md",
          "IMPLEMENTATION_COMPLETE.md",
          "IMPLEMENTATION_SUMMARY.md",
          "INTELLIGENCE_SELF_ASSESSMENT_2026-07-24.md",
          "PLATFORM_ACCELERATION_REVIEW.md",
          "REWORK-LEGAL-QAFIX-SLICE-4-TRANSPLANT-9D414CE.md"
        ],
        "changes_total": 100,
        "head": "b431cb921b633fcd939ea82d47c5c47926ede3a2",
        "kind": "dirty_worktree",
        "newest_change_mtime": 0,
        "path": "/Users/kpasch/Documents/tomorrow/tomorrow-wt/session-proof-of-work"
      },
      {
        "branches_digest": "84ea1d5ff67deba2cbaf153739e2afdb95e3fda130a8e4958a6fc39792386cda",
        "branches_sample": [
          {
            "committed_at": 1786013209,
            "ref": "agent/backlog-batch-tomorrow-2250a1e-adapt-prior-diffs-generate-diff-patch",
            "sha": "5348437bc02c6cd27a174dd7d38511f7c52d7b9f",
            "subject": "agent: backlog-batch-tomorrow-2250a1e-adapt-prior-diffs-generate-diff-patch"
          },
          {
            "committed_at": 1785337319,
            "ref": "agent/cont-05cc78",
            "sha": "7662fcd8f326bd3e56a08f80aea2c41047f1b965",
            "subject": "fix(security): bake rgba opacity values into gradient to prevent compounding"
          },
          {
            "committed_at": 1786203669,
            "ref": "agent/dropbox-cross-app-hivemind-federation-one-market-shaped-intelligence-spine-in-tomorrow-privacy-preserving-entity-reso",
            "sha": "86ba45a5fdaf340c4286e554583dc943268b73a6",
            "subject": "recovery-intent-stub: dropbox-cross-app-hivemind-federation-one-market-shaped-intelligence-spine-in-tomorrow-privacy-preserving-entity-reso"
          },
          {
            "committed_at": 1786108583,
            "ref": "agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2-clean-108578",
            "sha": "c2fb99aea4228c4cc5814c4deb7a490f2cba45e3",
            "subject": "self-heal: clean files from agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2 (13 files)"
          },
          {
            "committed_at": 1786115649,
            "ref": "agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2-clean-115646",
            "sha": "178cc2c2e1073b15898b480eb0c06d5232b343e5",
            "subject": "self-heal: clean files from agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2 (13 files)"
          },
          {
            "committed_at": 1786115925,
            "ref": "agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2-clean-115922",
            "sha": "f0a8e45d3788eb030c6e1c69a6554c955616df78",
            "subject": "self-heal: clean files from agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2 (13 files)"
          },
          {
            "committed_at": 1786123050,
            "ref": "agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2-clean-123043",
            "sha": "e207bb1122c6b50f7f71b29f40576143c685d318",
            "subject": "self-heal: clean files from agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2 (13 files)"
          },
          {
            "committed_at": 1786123278,
            "ref": "agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2-clean-123275",
            "sha": "a97b80c7010dd01bb0fafe42c9070aa4f4b0da76",
            "subject": "self-heal: clean files from agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2 (13 files)"
          },
          {
            "committed_at": 1786123907,
            "ref": "agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2-clean-123902",
            "sha": "f0a3a50c31402452843c31f4d7cca0618075349f",
            "subject": "self-heal: clean files from agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2 (13 files)"
          },
          {
            "committed_at": 1786126740,
            "ref": "agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2-clean-126731",
            "sha": "b01a898d992a688f457aca41a207433a7332ca93",
            "subject": "self-heal: clean files from agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2 (13 files)"
          },
          {
            "committed_at": 1786130206,
            "ref": "agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2-clean-130200",
            "sha": "652cf87335a53ce6e5b88eb67bcba25d84748d14",
            "subject": "self-heal: clean files from agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2 (13 files)"
          },
          {
            "committed_at": 1786133985,
            "ref": "agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2-clean-133980",
            "sha": "2b11347a733683e968928fd48baf3f2ce97b7722",
            "subject": "self-heal: clean files from agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2 (13 files)"
          },
          {
            "committed_at": 1786138974,
            "ref": "agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2-clean-138970",
            "sha": "75ff21190154116c0fd848b1589e8f487808b170",
            "subject": "self-heal: clean files from agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2 (13 files)"
          },
          {
            "committed_at": 1786140949,
            "ref": "agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2-clean-140946",
            "sha": "b6006a7e011bb56e7f2b5f3f1bfffe2a1164f1f8",
            "subject": "self-heal: clean files from agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2 (13 files)"
          },
          {
            "committed_at": 1786141317,
            "ref": "agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2-clean-141313",
            "sha": "a5fa12c899f49f795f5a38804213c8851f80d458",
            "subject": "self-heal: clean files from agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2 (13 files)"
          },
          {
            "committed_at": 1786141443,
            "ref": "agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2-clean-141438",
            "sha": "5c5d20597d1d7c1d41da572d98ea3c06fdb25931",
            "subject": "self-heal: clean files from agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2 (13 files)"
          },
          {
            "committed_at": 1786144035,
            "ref": "agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2-clean-144029",
            "sha": "4616a1ede7f97d302958e1a7b76d14ffcdc1a34a",
            "subject": "self-heal: clean files from agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2 (13 files)"
          },
          {
            "committed_at": 1786155533,
            "ref": "agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2-clean-155526",
            "sha": "df0a369c3dacfcc1a2d81dcf5848d392b97915d9",
            "subject": "self-heal: clean files from agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2 (13 files)"
          },
          {
            "committed_at": 1786165853,
            "ref": "agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2-clean-165847",
            "sha": "757b0849d230562b2ea95b16640a0afb6b75e9f0",
            "subject": "self-heal: clean files from agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2 (13 files)"
          },
          {
            "committed_at": 1786185620,
            "ref": "agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2-clean-185617",
            "sha": "8b4402816c7bbb4e6122e26d9e286344885d50b7",
            "subject": "self-heal: clean files from agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2 (13 files)"
          },
          {
            "committed_at": 1786169955,
            "ref": "agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2-patch-attorneycockpit",
            "sha": "0782234e83f2892021e1eb876fdc389a82438014",
            "subject": "regen-from-cache(template): dropbox-economic-scheduler-revenue-revenue-focused-slice-2-patch-attorneycockpit"
          },
          {
            "committed_at": 1786108748,
            "ref": "agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-3",
            "sha": "a31817cbdc6136514ff4c55db2a47ad57d5e7f26",
            "subject": "recovery-intent-stub: dropbox-economic-scheduler-revenue-revenue-focused-slice-3"
          },
          {
            "committed_at": 1786015069,
            "ref": "agent/dropbox-p0-t11-fix-ui-to-missing-route-calls",
            "sha": "47718dc5095e1f163d2610b99542c14e318db992",
            "subject": "agent: dropbox-p0-t11-fix-ui-to-missing-route-calls \u2014 rebase onto main, restore db:check literal"
          },
          {
            "committed_at": 1786015243,
            "ref": "agent/dropbox-p0-t7-migrate-dev-only-nitro-plugins-to-crons",
            "sha": "12730551915d97ac28535338b131c86885229497",
            "subject": "agent: dropbox-p0-t7-migrate-dev-only-nitro-plugins-to-crons \u2014 cover the remaining scheduler plugins"
          },
          {
            "committed_at": 1786093842,
            "ref": "agent/dropbox-pareto-2080-luxury-consigliere-repositioning-5m-ecp-passport-notes",
            "sha": "2fb35a148e8b34e750ae39f3d89014204c3b8642",
            "subject": "regen-from-cache(template): dropbox-pareto-2080-luxury-consigliere-repositioning-5m-ecp-passport-notes-paret"
          },
          {
            "committed_at": 1786093842,
            "ref": "agent/dropbox-pareto-2080-luxury-consigliere-repositioning-5m-ecp-passport-notes-paret",
            "sha": "2fb35a148e8b34e750ae39f3d89014204c3b8642",
            "subject": "regen-from-cache(template): dropbox-pareto-2080-luxury-consigliere-repositioning-5m-ecp-passport-notes-paret"
          },
          {
            "committed_at": 1786117991,
            "ref": "agent/dropbox-pareto-2080-luxury-consigliere-repositioning-5m-ecp-passport-notes-stand",
            "sha": "340164d390b7964dd3bf954434335a649d98035b",
            "subject": "recovery-intent-stub: dropbox-pareto-2080-luxury-consigliere-repositioning-5m-ecp-passport-notes-stand"
          },
          {
            "committed_at": 1786206058,
            "ref": "agent/dropbox-portfolio-doctrine-shared-services-x-items-slice-1",
            "sha": "0aa20013b1321d7c28ab7d93817f83e7a527be80",
            "subject": "recovery-intent-stub: dropbox-portfolio-doctrine-shared-services-x-items-slice-1"
          },
          {
            "committed_at": 1786203494,
            "ref": "agent/dropbox-tomorrow-foulkon-hedge-bridge-transferspec-population-1-clic-group-1",
            "sha": "a5a62b2edc32e36a4c2e4107712f6dc59b993e09",
            "subject": "recovery-intent-stub: dropbox-tomorrow-foulkon-hedge-bridge-transferspec-population-1-clic-group-1"
          },
          {
            "committed_at": 1786203573,
            "ref": "agent/dropbox-tomorrow-foulkon-hedge-bridge-transferspec-population-1-clic-group-2",
            "sha": "269298af311ab8e85fb1d51d15f30edd378af87a",
            "subject": "recovery-intent-stub: dropbox-tomorrow-foulkon-hedge-bridge-transferspec-population-1-clic-group-2"
          }
        ],
        "branches_total": 41,
        "count": 41,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/tomorrow/tomorrow"
      },
      {
        "count": 283,
        "items_digest": "e59378f2ab15b0119eab96ed8442973b1dfca27d996a687c0c83841579c52ce7",
        "items_sample": [
          {
            "created_at": 1785715617,
            "ref": "refs/orch-rescue/20260803T000657-6973da69fb225e176b92",
            "sha": "023ed58f67021a65c275fcec9618f503332c6883",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715617,
            "ref": "refs/orch-rescue/20260803T000657-tomorrow",
            "sha": "70fc9e5fe9056fbfd799121b42ab86cecdb48df4",
            "subject": "On main: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715617,
            "ref": "refs/orch-rescue/20260803T000700-6973da69fb225e176b92-run-28297-1785712211421632000",
            "sha": "9833650fc703a4511f8c7458c2665417b6a6e3a3",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715621,
            "ref": "refs/orch-rescue/20260803T000701-6973da69fb225e176b92-run-35951-1785712660470125000",
            "sha": "d7e30b8cbdcd231ec257cc112a36cc4876d1ddfe",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715621,
            "ref": "refs/orch-rescue/20260803T000701-breach-remediation",
            "sha": "efc7b86752bc9ca2b7c44863474ca877ec5116a8",
            "subject": "On agent/breach-remediation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715621,
            "ref": "refs/orch-rescue/20260803T000701-cade-mirror-negotiation",
            "sha": "3fdbdf403ac97b21c00f8eaf8e7923f0bbe8cf0c",
            "subject": "On agent/cade-mirror-negotiation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715622,
            "ref": "refs/orch-rescue/20260803T000702-cc-legacy-margin-removal",
            "sha": "ce9aeecf2eb3e90511930a54f758ad3bd6f11c3e",
            "subject": "On agent/cc-legacy-margin-removal: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715622,
            "ref": "refs/orch-rescue/20260803T000702-cc-mutual-default-fund",
            "sha": "f266db93417bdcd1f644f93a1bb2bc78d99f72a3",
            "subject": "On agent/cc-mutual-default-fund: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715623,
            "ref": "refs/orch-rescue/20260803T000703-cc-solvency-passport",
            "sha": "6fe98a742871802d07158854679f76d12412b76a",
            "subject": "On agent/cc-solvency-passport: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715623,
            "ref": "refs/orch-rescue/20260803T000703-convention-conformance-lints",
            "sha": "05c1b890d91e9fb4870c13fe655a0e5c32bc6999",
            "subject": "On agent/convention-conformance-lints: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715623,
            "ref": "refs/orch-rescue/20260803T000703-curation-institutiontype-persist",
            "sha": "0d9cec79430ba3d092e90eb24a20e2eb9a53ca39",
            "subject": "On agent/curation-institutiontype-persist: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715624,
            "ref": "refs/orch-rescue/20260803T000704-economic-scheduler-revenue",
            "sha": "db8857517adf5330ff3adae7c1eabd9931a6ae46",
            "subject": "On agent/economic-scheduler-revenue: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715624,
            "ref": "refs/orch-rescue/20260803T000704-ensemble-on-hard",
            "sha": "933439f7190511266e657b18b3dd745f8c61a603",
            "subject": "On agent/ensemble-on-hard: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715624,
            "ref": "refs/orch-rescue/20260803T000704-ext-streaming-terms",
            "sha": "78b80f620b26931b2bbadb49b37ef8992c934a49",
            "subject": "On agent/ext-streaming-terms: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715624,
            "ref": "refs/orch-rescue/20260803T000704-fix-golden-syntax",
            "sha": "f8524ef083b2dcceb13bf2f6739faf87e745a86d",
            "subject": "On fix/conviction-core-golden-syntax: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715624,
            "ref": "refs/orch-rescue/20260803T000704-fix-syntax-lint-scope",
            "sha": "2304fa3d4616348868a1da1d64f212e2303c8d28",
            "subject": "On fix/syntax-lint-scope: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715625,
            "ref": "refs/orch-rescue/20260803T000705-hive-enforcement-velocity-index",
            "sha": "0e6d41fb0a7c2c5a80ec3fae8dbb3289e24cf193",
            "subject": "On agent/hive-enforcement-velocity-index: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715625,
            "ref": "refs/orch-rescue/20260803T000705-merged-diff-memory",
            "sha": "2834a4b60748f25bc8207b363c07d2384b717b31",
            "subject": "On agent/merged-diff-memory: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715626,
            "ref": "refs/orch-rescue/20260803T000706-orch-config-consumption",
            "sha": "be942de97ce0c49ca55ee34c445c3e40d7f58b28",
            "subject": "On agent/orch-config-consumption: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715626,
            "ref": "refs/orch-rescue/20260803T000706-pinned-express-lane",
            "sha": "83791d8a5d941207957ec1e4a4988d7ac26be2c4",
            "subject": "On agent/pinned-express-lane: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715627,
            "ref": "refs/orch-rescue/20260803T000707-ploeh-s2s-bridge-tomorrow",
            "sha": "4311b02c9c6a4fdb2ef2c07283993c47ed522778",
            "subject": "On agent/ploeh-s2s-bridge-tomorrow: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715627,
            "ref": "refs/orch-rescue/20260803T000707-predictive-preemption",
            "sha": "39da964835be21316602687ca6057cad9fe2f030",
            "subject": "On agent/predictive-preemption: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715628,
            "ref": "refs/orch-rescue/20260803T000708-prompt-evolution-bandit",
            "sha": "881df542e6b12105f9d2bece20297413783de8b5",
            "subject": "On agent/prompt-evolution-bandit: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715629,
            "ref": "refs/orch-rescue/20260803T000709-smarter-5-95",
            "sha": "b2d3cfca656e0f6034b9bed22fcdc4476269852b",
            "subject": "On agent/smarter-5-95: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715664,
            "ref": "refs/orch-rescue/20260803T000744-tomorrow",
            "sha": "248206db911914064121a377008a2b307edcb9f2",
            "subject": "On main: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715665,
            "ref": "refs/orch-rescue/20260803T000745-6973da69fb225e176b92",
            "sha": "aa6d32a73dff4ccdc09f0a7b284a6c3328a7c82c",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715665,
            "ref": "refs/orch-rescue/20260803T000746-6973da69fb225e176b92-run-28297-1785712211421632000",
            "sha": "450bf3f7718c3f9af3b0ad1e7beb771698fdd79a",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715666,
            "ref": "refs/orch-rescue/20260803T000746-6973da69fb225e176b92-run-35951-1785712660470125000",
            "sha": "eeb7397e7ca2e1b826b4e65441f2706b167779e2",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715666,
            "ref": "refs/orch-rescue/20260803T000746-breach-remediation",
            "sha": "7d35dda6e5582bd55ad27cbcb657ea4c36882bfb",
            "subject": "On agent/breach-remediation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715667,
            "ref": "refs/orch-rescue/20260803T000747-cade-mirror-negotiation",
            "sha": "1dd02d57bbd4eb886b286c5208328b87b8a7a4c3",
            "subject": "On agent/cade-mirror-negotiation: orch-rescue: periodic sweep"
          }
        ],
        "items_total": 283,
        "kind": "orchestrator_rescue_refs",
        "repo": "/Users/kpasch/Documents/tomorrow/tomorrow"
      }
    ]
