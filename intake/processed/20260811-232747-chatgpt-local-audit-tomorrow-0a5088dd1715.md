PROJECT: tomorrow

- id: chatgpt-local-reconcile-tomorrow-0a5088dd1715
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
    `0a5088dd17156ea0357ac57579ba1bb4faa8f716c769ffa049f0ba5447c3cb13`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "DETACHED",
        "change_count": 1,
        "changes": [
          "packages/curation-core/node_modules/.vite/vitest/da39a3ee5e6b4b0d3255bfef95601890afd80709/results.json"
        ],
        "changes_digest": "57f90ec4d4c0896116a6af3cb2ad565771de743f6f1f96c35b413e7db8bbe304",
        "head": "a933b66597175ac3b323c8d5cce75614b171e063",
        "kind": "dirty_worktree",
        "newest_change_mtime": 0,
        "path": "/Users/kpasch/Documents/beethoven/claude-orchestrator/.runtime/integration-worktrees/6973da69fb225e176b92"
      },
      {
        "branch": "landing-revamp-20260811",
        "change_count": 57,
        "changes_digest": "df355c55dcc0a6ecf7a41966f06bd4b4a1c66362cd4a17b7f74491a1e22fc380",
        "changes_sample": [
          "_to_delete/HEAD.lock.5",
          "articles/_archive/TOPIC-LEDGER.md",
          "articles/_archive/run-reports/2026-08-11.md",
          "articles/medium/2026-08-11_the-morning-the-exchange-unwound-the-market.md",
          "articles/medium/2026-08-11_the-pitch-and-the-pennant.md",
          "components/v2/AppSidebar.vue",
          "composables/useConvictionIntel.ts",
          "composables/useGamification.ts",
          "composables/useMemberCredit.ts",
          "composables/usePositionManager.ts",
          "composables/useUserRole.ts",
          "pages/app/benefits/index.vue",
          "pages/app/board/index.vue",
          "pages/app/intelligence/index.vue",
          "pages/app/leverage/index.vue",
          "pages/app/positions/index.vue",
          "pages/login.vue",
          "prisma/migrations/20260808_alter_position_derivative_columns/migration.sql",
          "prisma/migrations/20260808_gamification_tables/migration.sql",
          "prisma/migrations/20260808_positions_credit_intel/migration.sql",
          "server/api/v2/benefits/events/[id]/rsvp.post.ts",
          "server/api/v2/credit/draw.post.ts",
          "server/api/v2/credit/free-taste.get.ts",
          "server/api/v2/credit/free-taste/claim.post.ts",
          "server/api/v2/credit/perks.get.ts",
          "server/api/v2/credit/referral.get.ts",
          "server/api/v2/credit/referral/link.post.ts",
          "server/api/v2/credit/summary.get.ts",
          "server/api/v2/gamification/activity.post.ts",
          "server/api/v2/gamification/near-misses.get.ts"
        ],
        "changes_total": 57,
        "head": "a933b66597175ac3b323c8d5cce75614b171e063",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786417864,
        "path": "/Users/kpasch/Documents/tomorrow/tomorrow"
      },
      {
        "branches_digest": "2ac351a8f4d953b5bb3e6922de6c65b97c969f200759b3c6e85850848b3f3ca9",
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
        "branches_total": 39,
        "count": 39,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/tomorrow/tomorrow"
      },
      {
        "count": 266,
        "items_digest": "30f68fa59a6d17d342ce10405170c46b900d18a1e1818418343f4aa73e4d2a63",
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
        "items_total": 266,
        "kind": "orchestrator_rescue_refs",
        "repo": "/Users/kpasch/Documents/tomorrow/tomorrow"
      },
      {
        "count": 40,
        "items_digest": "419a54df1a7f2e076be079fc635b2f7c62b0a07fdf31559ce09e58f27fe75796",
        "items_sample": [
          {
            "created_at": 1784742125,
            "ref": "stash@{0}",
            "sha": "2cd78e17c8a365dc124e0a50741399080aa28925",
            "subject": "WIP on main: e683890f99 Include runtime export guard in Vercel builds"
          },
          {
            "created_at": 1784741910,
            "ref": "stash@{1}",
            "sha": "dcffee0b2d580d223d8122efab145982372d6dee",
            "subject": "WIP on main: 114a6c081a fix(build #24): add 144 stub exports across 22 files \u2014 bulk MISSING_EXPORT fix"
          },
          {
            "created_at": 1784739036,
            "ref": "stash@{2}",
            "sha": "8e6dedd47f4ed7975bffbd66795d3865121899e1",
            "subject": "WIP on main: 9ff44d1aea fix(build): add missing onAutoSkipApproved/onAutoSkipRejected exports to autoSkipGate.ts"
          },
          {
            "created_at": 1784739023,
            "ref": "stash@{3}",
            "sha": "0393f53c77e20af388edb218def236236f6e710f",
            "subject": "On main: all changes before rebase"
          },
          {
            "created_at": 1784739016,
            "ref": "stash@{4}",
            "sha": "614cfe6fe203351090a757da516c43f63defd1d9",
            "subject": "On main: node_modules changes before rebase"
          },
          {
            "created_at": 1784739011,
            "ref": "stash@{5}",
            "sha": "a6c983dc4f395f1b92b848b73b1b432e27987b4f",
            "subject": "WIP on main: 9ff44d1aea fix(build): add missing onAutoSkipApproved/onAutoSkipRejected exports to autoSkipGate.ts"
          },
          {
            "created_at": 1784738957,
            "ref": "stash@{6}",
            "sha": "117194ad9c737729f2a22800411aab7a72c8c23c",
            "subject": "WIP on main: 9ff44d1aea fix(build): add missing onAutoSkipApproved/onAutoSkipRejected exports to autoSkipGate.ts"
          },
          {
            "created_at": 1784699533,
            "ref": "stash@{7}",
            "sha": "9bcab60f554cf0bac007b76218bb726fb4a888d3",
            "subject": "WIP on main: 934b54645b Merge branch 'agent/deployfix-vercel-ignore-agent-branches-locate-template-2b8589a51fa1'"
          },
          {
            "created_at": 1784695407,
            "ref": "stash@{8}",
            "sha": "f62268028b1848ae429052d6efe8cd4a58b46576",
            "subject": "WIP on main: 0fff15a817 chore: add agent noise files to .gitignore, remove from tracking"
          },
          {
            "created_at": 1784695287,
            "ref": "stash@{9}",
            "sha": "5bfe23de27538a80e00cba3320219ccac08820c6",
            "subject": "WIP on main: 0fff15a817 chore: add agent noise files to .gitignore, remove from tracking"
          },
          {
            "created_at": 1784566224,
            "ref": "stash@{10}",
            "sha": "b82280c0343f4869175541258cddd62174173821",
            "subject": "WIP on main: 5ad886253 merge: fix/ci-baseline into main (resolved conflicts, accepted theirs)"
          },
          {
            "created_at": 1784346942,
            "ref": "stash@{11}",
            "sha": "8e37bdd812a1b44682594e50fba5471a74cb7a57",
            "subject": "WIP on main: 4b853bf4f agent: cade-tribunal-counterparty-inspect-existing-work-and-failure"
          },
          {
            "created_at": 1784183820,
            "ref": "stash@{12}",
            "sha": "f377d8a6501738b70ed7946d66179687407c9683",
            "subject": "WIP on agent/cross-vertical-offset-discovery: 2acb00efb feat(lending): add cross-vertical offset discovery module"
          },
          {
            "created_at": 1784180860,
            "ref": "stash@{13}",
            "sha": "29042af5df843160b32de57366b6a60c0ed3c8a3",
            "subject": "WIP on agent/rework-legal-rework-secret-qafix-tomorrow-07062319-b136250-f9c7e69: 91502905d fix: use npx for vitest to ensure command resolution"
          },
          {
            "created_at": 1784178921,
            "ref": "stash@{14}",
            "sha": "8afae9ad3b1c0bbb3b01581a58b9c19ccd43902a",
            "subject": "WIP on main: 80d18c6a3 feat: add ECP Prisma models, migration, and DB-primary persistence with KV fallback"
          },
          {
            "created_at": 1784170651,
            "ref": "stash@{15}",
            "sha": "4700a51087cdf5e5e6b8e7198527dc854261a3f1",
            "subject": "WIP on warranty-settlement-implement-comprehensive-unit-tests: 3b45f023e fix: whitelist better-sqlite3 (+prisma/esbuild) build scripts for pnpm v10 \u2014 native bindings now compile on Vercel"
          },
          {
            "created_at": 1784170227,
            "ref": "stash@{16}",
            "sha": "4ae9b1e8eea25b8f1e9b52d980197471915a588a",
            "subject": "WIP on sw-number-lineage-short-kebab-title: 246be2cdb Add authenticated VIGIL receiver"
          },
          {
            "created_at": 1784170098,
            "ref": "stash@{17}",
            "sha": "cf46cd76a5da48faa4f8714ddba15ae3153e199a",
            "subject": "WIP on oracle-indices-as-underlyings: 5d158ac30 feat: rateIndexUnderlying \u2014 rate-index-settled bilateral ECP swaps with drift gate + proof-carrying settlement"
          },
          {
            "created_at": 1784150139,
            "ref": "stash@{18}",
            "sha": "3c04af9f2fad0039864b3e5ced4e1f5d1f70e6cb",
            "subject": "WIP on session/perp-wired-1784149001: 123cc16d3 fix(ecp-coordination-hygiene): correct ecpCredentialing test score expectation"
          },
          {
            "created_at": 1784137671,
            "ref": "stash@{19}",
            "sha": "ff4397a35a6dc930ba9354bb0016c44ba0d64249",
            "subject": "WIP on main: 3b45f023 fix: whitelist better-sqlite3 (+prisma/esbuild) build scripts for pnpm v10 \u2014 native bindings now compile on Vercel"
          },
          {
            "created_at": 1784047807,
            "ref": "stash@{20}",
            "sha": "cd8c23bfef82a0ad2a2cfa44da7690bdc420063b",
            "subject": "WIP on main: 3b45f023 fix: whitelist better-sqlite3 (+prisma/esbuild) build scripts for pnpm v10 \u2014 native bindings now compile on Vercel"
          },
          {
            "created_at": 1784040589,
            "ref": "stash@{21}",
            "sha": "fc41bca9d2f58777b2cb6446a4745556750372cd",
            "subject": "WIP on agent/capital-relief-filing-exhibit: 3b45f023 fix: whitelist better-sqlite3 (+prisma/esbuild) build scripts for pnpm v10 \u2014 native bindings now compile on Vercel"
          },
          {
            "created_at": 1784035868,
            "ref": "stash@{22}",
            "sha": "7ce3eb39fde9bcc82d39ecd953d75b09f3d3c5cf",
            "subject": "WIP on agent/determinations-engine-spec: 8036ad9a fix(build): lower build Node heap 7168->6144 to avoid Vercel builder OOM"
          },
          {
            "created_at": 1784032377,
            "ref": "stash@{23}",
            "sha": "26f707699a2ed5e73c86c55cde19b28c80b5ac35",
            "subject": "WIP on agent/command-bar-ui: 5cf0c10b feat: seed corpus_source_state with historical sources"
          },
          {
            "created_at": 1784003314,
            "ref": "stash@{24}",
            "sha": "190bbf76d34dd7f0e2bdc402d03e9f805413b233",
            "subject": "WIP on agent/ecp-lock-branch: 3b45f023 fix: whitelist better-sqlite3 (+prisma/esbuild) build scripts for pnpm v10 \u2014 native bindings now compile on Vercel"
          },
          {
            "created_at": 1783999510,
            "ref": "stash@{25}",
            "sha": "222aeb082ec87fd6bb261a5873eff757d0917ea3",
            "subject": "WIP on agent/oracle-ingest-pareto-indices: 3b45f023 fix: whitelist better-sqlite3 (+prisma/esbuild) build scripts for pnpm v10 \u2014 native bindings now compile on Vercel"
          },
          {
            "created_at": 1783987382,
            "ref": "stash@{26}",
            "sha": "136f81dc8c0df6e0f60b7916937379f48d1bd28d",
            "subject": "WIP on agent/rework-legal-rework-secret-qafix-tomorrow-07062319-b136250-f9c7e69: 482c3041 fix: use npx for vitest to ensure command resolution"
          },
          {
            "created_at": 1783979733,
            "ref": "stash@{27}",
            "sha": "d7703eb99ccb02fcb2ae74668c5a97f8b00b1013",
            "subject": "WIP on agent/bx1-batch: bf8f1287 feat: implement trust-ratchet learning-mode system"
          },
          {
            "created_at": 1783977069,
            "ref": "stash@{28}",
            "sha": "4cfd2c17dd6f8638813f318edd73819364d94c98",
            "subject": "WIP on agent/bx1-batch: be5548d5 agent/bx1: tomorrow-shared-curation-extract, tomorrow-curation-warroom-bridge, tomorrow-warroom-remediation-playbook"
          },
          {
            "created_at": 1783955829,
            "ref": "stash@{29}",
            "sha": "2595f8ad450c1a19e39a78afcb87baa2aabe710e",
            "subject": "WIP on agent/bx3-tomorrow-tasks: b9009174 agent/bx3: sw-contracts sw-netting-utility-api sw-systemic-riskmap sw-stability-simulator sw-demand-foresight-feed"
          }
        ],
        "items_total": 40,
        "kind": "stashes",
        "repo": "/Users/kpasch/Documents/tomorrow/tomorrow"
      },
      {
        "branches": [
          {
            "committed_at": 1784857649,
            "ref": "codex/release-dashboard-auth-20260723",
            "sha": "5c5b3c7a1eb0aba06e759899ecfa1cb79892a4d2",
            "subject": "fix(compliance): unblock access acknowledgment"
          }
        ],
        "count": 1,
        "kind": "unmerged_chatgpt_codex_branches",
        "repo": "/Users/kpasch/Documents/tomorrow/tomorrow"
      }
    ]
