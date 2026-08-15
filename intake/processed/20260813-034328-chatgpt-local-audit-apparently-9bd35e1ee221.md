PROJECT: apparently

- id: chatgpt-local-reconcile-apparently-9bd35e1ee221
  title: Reconcile local ChatGPT/Codex build evidence for apparently
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
    `9bd35e1ee22158d8c4b4b0740a3f1a95724e2756b0285bdf35f6a784e56dab15`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "agent/merged-diff-memory",
        "change_count": 1014,
        "changes_digest": "6b441a3d7de6d774cc2c2e8645e9b48d6b8fcc94e39217bdbf35b23c9d93a76b",
        "changes_sample": [
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-diagnose.mjs",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-exec.mjs",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-probe-current.mjs",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-probe-ecstatic.mjs",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-probe-sjd.mjs",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-probe.mjs",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-report-2026-04-25.md",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-report-2026-04-25T22-57Z.md",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-report-2026-04-25T23-13Z.md",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-report-2026-04-25T23-39Z.md",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-report-2026-04-25T23-55Z.md",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-report-2026-04-26T00-09Z.md",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-report-2026-04-26T19-38Z.md",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-report-2026-04-26T19-39Z.md",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-report-2026-04-26T19-40Z.md",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-run-2026-04-24-heisenberg.mjs",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-run-2026-04-24.mjs",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-run-2026-04-25-amazing-nifty-clarke.mjs",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-run-2026-04-25-brave-inspiring-mccarthy.mjs",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-run-2026-04-25-dazzling-busy-sagan.mjs",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-run-2026-04-25-exciting-loving-cerf.mjs",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-run-2026-04-25-funny-relaxed-noether.mjs",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-run-2026-04-25-gallant-upbeat-hawking.mjs",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-run-2026-04-25-gracious-adoring-ride.mjs",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-run-2026-04-25-great-upbeat-darwin.mjs",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-run-2026-04-25-happy-dreamy.mjs",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-run-2026-04-25-intelligent-epic-hawking.mjs",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-run-2026-04-25-intelligent-wizardly-gates.mjs",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-run-2026-04-25-magical-pasteur.mjs",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-run-2026-04-25-modest-sharp-allen.mjs"
        ],
        "changes_total": 100,
        "head": "a00ed90002d9568fc685620b85e43e1ee6f9fea9",
        "kind": "dirty_worktree",
        "newest_change_mtime": 0,
        "path": "/Users/kpasch/Documents/apparently-wt/merged-diff-memory"
      },
      {
        "branch": "agent/p0-oauth-ssr-session-cookie-persistence-20260808",
        "change_count": 5,
        "changes": [
          "_dormant/citation-integration.ts",
          "_dormant/streaming-response.ts",
          "ops-rlo-accuracy-dashboard.html",
          "ops-throughput-dashboard.html",
          "ops-triage-dashboard.html"
        ],
        "changes_digest": "2a515b163b6aba4143dc42e9ffb661bf6c499d37e0c16947a8addcb1a2fdf73a",
        "head": "37c62569d4cb333778b866b871dd283f3390d534",
        "kind": "dirty_worktree",
        "newest_change_mtime": 0,
        "path": "/Users/kpasch/Documents/apparently-wt/oauthssr"
      },
      {
        "count": 29,
        "items": [
          {
            "created_at": 1785935220,
            "ref": "stash@{1}",
            "sha": "5e4c1bee9da5a2a3ee4ea503efd7e8145b7f7cfc",
            "subject": "On agent/cc-solvency-passport: wip-agent-branch-1785935220"
          },
          {
            "created_at": 1785676921,
            "ref": "stash@{2}",
            "sha": "0ce89f31c993c4c473fc64934c03f561c00eceac",
            "subject": "WIP on master: 2dd3a3e0 Merge branch 'agent/backlog-batch-apparently-0ef7cd6-kpi-dashboard-recovery-analyze-and-select-diff-' (auto-resolved)"
          },
          {
            "created_at": 1785587051,
            "ref": "stash@{3}",
            "sha": "e891267ee37bcdea5cd62307d91227ca37c64335",
            "subject": "WIP on master: eee30c74 merge: Stripe webhook middleware exemptions (payments launch fix)"
          },
          {
            "created_at": 1785553645,
            "ref": "stash@{4}",
            "sha": "a3a3a55fe126775b2715f58123fab2a2459d89d3",
            "subject": "WIP on master: eee30c74 merge: Stripe webhook middleware exemptions (payments launch fix)"
          },
          {
            "created_at": 1785512030,
            "ref": "stash@{5}",
            "sha": "09785230d086c507155f1292f5832a3df343a25a",
            "subject": "On agent/hive-support-entity-relationship-source: agent-wip-guard"
          },
          {
            "created_at": 1785510761,
            "ref": "stash@{6}",
            "sha": "b2a65205cb8a4b006c41533ed25ef5abe80d9f4d",
            "subject": "WIP on agent/act-e2e-usable-smoke: e8e4d34f fix(e2e-hive-usable): remove networkidle waits and simplify async patterns to prevent timeout"
          },
          {
            "created_at": 1785468869,
            "ref": "stash@{7}",
            "sha": "04d74d7f992279e4912a136e6a610b1300407ac2",
            "subject": "WIP on agent/hive-support-entity-relationship-source: 39101f3e fix(hive): correct entity-relationship-source test for missing orgLabel scenario"
          },
          {
            "created_at": 1785368694,
            "ref": "stash@{8}",
            "sha": "890df2fb6a7cebb7dd5d9a25f1b2b3e5812e9841",
            "subject": "WIP on agent/hive-support-entity-relationship-source: ca99b50c feat(hive): add entity-relationship-source fetcher and support-entity orchestration"
          },
          {
            "created_at": 1784991314,
            "ref": "stash@{9}",
            "sha": "ac18c82dc0f72ee40299ca083cbcd6c8be1223aa",
            "subject": "WIP on agent/cade-tribunal-counterparty-validate-batch-release--slice-2: 0b78d1db Merge branch 'master' of https://github.com/kalepasch1/apparently"
          },
          {
            "created_at": 1784755574,
            "ref": "stash@{10}",
            "sha": "806f4197fb5f286d7b6ec8b9b2fc21abc4f6c0b8",
            "subject": "On master: auto-stash before merge"
          },
          {
            "created_at": 1784686643,
            "ref": "stash@{11}",
            "sha": "9cdde87ad6352e20333c8b5ce6e6263d9017084a",
            "subject": "WIP on master: 8c26ce22 Merge branch 'worktree-agent-a8881439b52c6ca1d'"
          },
          {
            "created_at": 1784684715,
            "ref": "stash@{12}",
            "sha": "edd1a0734a4ed319e0b9e446f7026292fef1bdfb",
            "subject": "On master: pre-force-merge"
          },
          {
            "created_at": 1784565776,
            "ref": "stash@{13}",
            "sha": "0b7472d65e7ecdb6a985d76884dd1116d89e4270",
            "subject": "WIP on master: 9e7c4ad chore: commit uncommitted production changes"
          },
          {
            "created_at": 1784426674,
            "ref": "stash@{14}",
            "sha": "6039f593c4701ff807f3d2d37a922e8fe8d50a42",
            "subject": "WIP on agent/recover-missing-branch-corpus-metered-api-slice-2: da7fb11 feat: add metered corpus GET endpoint with usage tracking and rate limiting"
          },
          {
            "created_at": 1784416778,
            "ref": "stash@{15}",
            "sha": "1ef4684aae0ec80d020b738d50ebd0d25c5b4804",
            "subject": "WIP on master: a2d506f CADE expert mesh: 613K virtual experts, daily evolution cron, research tools, Ollama adapter"
          },
          {
            "created_at": 1784207993,
            "ref": "stash@{16}",
            "sha": "67138a2364e2940597262cdc45a63b529d42f11f",
            "subject": "WIP on agent/hive-ops-dashboards-exposures-and-regulatory-debt-panels: 7866c0a train: agent/pii-encryption-and-portal-rls-slice-1"
          },
          {
            "created_at": 1784192062,
            "ref": "stash@{17}",
            "sha": "0ccff4ac4fa94d8581a886ab54361f969bbe1d00",
            "subject": "WIP on master: a2d506f CADE expert mesh: 613K virtual experts, daily evolution cron, research tools, Ollama adapter"
          },
          {
            "created_at": 1784184024,
            "ref": "stash@{18}",
            "sha": "6a5f146d6e018c881663b8d02b8ee5e3e2938c1e",
            "subject": "WIP on agent/ploeh-s2s-bridge-apparently: 99474a9 feat: PLOEH S2S bridge with HMAC-SHA256 signing"
          },
          {
            "created_at": 1784181393,
            "ref": "stash@{19}",
            "sha": "e71961458a2ac1cbe305fbbc37c13fc11700e493",
            "subject": "WIP on master: e02c589 feat: add regulator cooperation handoff"
          },
          {
            "created_at": 1784176640,
            "ref": "stash@{20}",
            "sha": "8f7620851760e8d00106a3d96ed15ceaecf07183",
            "subject": "WIP on agent/rework-secret-rework-secret-license-passport-ad7131a-fb5b135: 82d431d docs: backlog batch consolidation 5bb26b4"
          },
          {
            "created_at": 1784176000,
            "ref": "stash@{21}",
            "sha": "d879de782eda04a758d10a49ebcd6a833ba95762",
            "subject": "WIP on recovery/concurrent-primary-20260715-apparently: cd565ab feat: schedule autonomous License OS factory"
          },
          {
            "created_at": 1784149374,
            "ref": "stash@{22}",
            "sha": "a66858a2810a08ca0f481b35afbc2614368faa5e",
            "subject": "WIP on agent/backlog-batch-apparently-e5d4a9c: c24ffce docs: backlog batch consolidation e5d4a9c"
          },
          {
            "created_at": 1784047102,
            "ref": "stash@{23}",
            "sha": "a7fbebaeef6fdcb90a5f4cd19c5b6152b007c102",
            "subject": "WIP on agent/rework-secret-rework-secret-license-passport-ad7131a-fb5b135: c2778e1 feat(license-passport): add informational license passport with public verify"
          },
          {
            "created_at": 1784042979,
            "ref": "stash@{24}",
            "sha": "5d1536dcab08ade67285216a26d3021493778540",
            "subject": "WIP on master: ed0dc42 agent/bx1: cade-decider-twin, cade-voi-intake-ui"
          },
          {
            "created_at": 1784003210,
            "ref": "stash@{25}",
            "sha": "b03a64a9fc755aa3211ea1ca09b4a5169fe784cd",
            "subject": "WIP on agent/position-outcome-endpoint-split-the-build-task-int-slice-1: 93d8c50 fix: correct supabase-typed import path (supabase-client does not exist) \u2014 unblocks nitro build"
          },
          {
            "created_at": 1783986858,
            "ref": "stash@{26}",
            "sha": "4f3daebd794cfb092cca14bbc261dac2a0584754",
            "subject": "WIP on agent/qafix-apparently-07130648: cf3aa40 agent/cade-league-eval-set-slice-2: add adversary-league-eval.test.ts pinning league routing determinism"
          },
          {
            "created_at": 1783310575,
            "ref": "stash@{27}",
            "sha": "5d1e94f7320752641ee0e08d2d1b121b43964f2f",
            "subject": "On master: recover_and_ship: pre-merge dirt 1783310575"
          },
          {
            "created_at": 1782317057,
            "ref": "stash@{28}",
            "sha": "298ead8c025e1edd9dc722008aa6eb514bff2269",
            "subject": "WIP on feat/source-of-truth-50x: 50da2c3 fix(security): revoke anon EXECUTE on SECURITY DEFINER functions + matview ACL"
          },
          {
            "created_at": 1782179784,
            "ref": "stash@{29}",
            "sha": "113e43caf69e88e7b91f7418879441117ed8e7a8",
            "subject": "On feat/source-of-truth-50x: runner-inflight-3b0e86c"
          }
        ],
        "kind": "stashes",
        "repo": "/Users/kpasch/Documents/apparently"
      }
    ]
