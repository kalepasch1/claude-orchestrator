PROJECT: tomorrow

- id: chatgpt-local-reconcile-tomorrow-1d281ec0a062
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
    `1d281ec0a0626bae0ad06d3dee4519aa3b0a22e1aa459371f3a1a3b7ee43318f`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branches_digest": "0d0f1d17ae1c67d7b7c2dacf8c1ef79c232f824dc842443c5fcfc243d8efd3d9",
        "branches_sample": [
          {
            "committed_at": 1786013209,
            "ref": "agent/backlog-batch-tomorrow-2250a1e-adapt-prior-diffs-generate-diff-patch",
            "sha": "5348437bc02c6cd27a174dd7d38511f7c52d7b9f",
            "subject": "agent: backlog-batch-tomorrow-2250a1e-adapt-prior-diffs-generate-diff-patch"
          },
          {
            "committed_at": 1786590381,
            "ref": "agent/bugfix-curation-institution-taxonomy-conflict",
            "sha": "daacf102739e477d05e4f882731908a2507b30c8",
            "subject": "agent: bugfix-curation-institution-taxonomy-conflict"
          },
          {
            "committed_at": 1786572878,
            "ref": "agent/chatgpt-local-reconcile-tomorrow-0a5088dd1715",
            "sha": "497b4a95143e2f99d90df86d2bc2abe3420d831e",
            "subject": "agent: chatgpt-local-reconcile-tomorrow-0a5088dd1715"
          },
          {
            "committed_at": 1786651941,
            "ref": "agent/chatgpt-local-reconcile-tomorrow-1959809d4e74-slice-1",
            "sha": "e62bd8ca798727006eb965d88e09e9f27112c8b4",
            "subject": "agent: chatgpt-local-reconcile-tomorrow-1959809d4e74-slice-1"
          },
          {
            "committed_at": 1786807457,
            "ref": "agent/chatgpt-local-reconcile-tomorrow-1d6cb3ae8666",
            "sha": "3ca30667a36edb2075e1c98512fb499569cfd9e5",
            "subject": "agent: chatgpt-local-reconcile-tomorrow-1d6cb3ae8666"
          },
          {
            "committed_at": 1786654202,
            "ref": "agent/chatgpt-local-reconcile-tomorrow-1fd5c3ff0bf2",
            "sha": "64c78dff5735408a74fbb3823bcf5200bb1c4a90",
            "subject": "agent: chatgpt-local-reconcile-tomorrow-1fd5c3ff0bf2"
          },
          {
            "committed_at": 1786799432,
            "ref": "agent/chatgpt-local-reconcile-tomorrow-2a509a6cf06c",
            "sha": "55b86e53092109eec1e511e89104c7464c5bac7e",
            "subject": "agent: chatgpt-local-reconcile-tomorrow-2a509a6cf06c"
          },
          {
            "committed_at": 1786573090,
            "ref": "agent/chatgpt-local-reconcile-tomorrow-39a7703a9f9c",
            "sha": "ad5f1814cc9342f507b4b46fb3e33d7d4e137892",
            "subject": "agent: chatgpt-local-reconcile-tomorrow-8ce35eb9ae43"
          },
          {
            "committed_at": 1786573065,
            "ref": "agent/chatgpt-local-reconcile-tomorrow-428d9cdff1e1",
            "sha": "4da50aa6ebd9948c6bbbb657c368c33c99f3c2ca",
            "subject": "agent: chatgpt-local-reconcile-tomorrow-8ce35eb9ae43"
          },
          {
            "committed_at": 1786653952,
            "ref": "agent/chatgpt-local-reconcile-tomorrow-4d4dec67d81f",
            "sha": "3e69b59edf05e178971cb3b8feaee2a24127385f",
            "subject": "agent: chatgpt-local-reconcile-tomorrow-4d4dec67d81f \u2014 exclude deletion-only sweep artifacts from recoverable value"
          },
          {
            "committed_at": 1786573060,
            "ref": "agent/chatgpt-local-reconcile-tomorrow-4dfa0e31aee5",
            "sha": "495e8dda4a913eb6e07e08bde9ea17fed9a77459",
            "subject": "agent: chatgpt-local-reconcile-tomorrow-8ce35eb9ae43"
          },
          {
            "committed_at": 1786680404,
            "ref": "agent/chatgpt-local-reconcile-tomorrow-62e3b89e03af",
            "sha": "20e2b01ebeda7efbb71c449807469a41cd4db295",
            "subject": "agent: chatgpt-local-reconcile-tomorrow-62e3b89e03af (executable completion criteria + baseline attribution evidence)"
          },
          {
            "committed_at": 1786803084,
            "ref": "agent/chatgpt-local-reconcile-tomorrow-b8f5cf32cb21",
            "sha": "8727d9eae6100e04a85866dd46e3e0089805eb4c",
            "subject": "agent: chatgpt-local-reconcile-tomorrow-b8f5cf32cb21"
          },
          {
            "committed_at": 1786610262,
            "ref": "agent/chatgpt-local-reconcile-tomorrow-c875b5d08a36",
            "sha": "b1bdef04532a1e1b7bbbe6e26ed0ce28766c59b9",
            "subject": "agent: chatgpt-local-reconcile-tomorrow-c875b5d08a36"
          },
          {
            "committed_at": 1786574605,
            "ref": "agent/chatgpt-local-reconcile-tomorrow-cadcf5dad7e9",
            "sha": "41867ba0499c298d02f386581bca603677e0d751",
            "subject": "agent: chatgpt-local-reconcile-tomorrow-8ce35eb9ae43"
          },
          {
            "committed_at": 1786805770,
            "ref": "agent/chatgpt-local-reconcile-tomorrow-cda468882594",
            "sha": "c7870cfadeb4f7654debc5b266b822ba93fc03bc",
            "subject": "agent: chatgpt-local-reconcile-tomorrow-cda468882594"
          },
          {
            "committed_at": 1786799232,
            "ref": "agent/chatgpt-local-reconcile-tomorrow-d1fe07cc7ffa",
            "sha": "9d5f2dcfdd611f2c33397223f68c954ccdcbc1b1",
            "subject": "agent: chatgpt-local-reconcile-tomorrow-d1fe07cc7ffa"
          },
          {
            "committed_at": 1786806763,
            "ref": "agent/chatgpt-local-reconcile-tomorrow-ff4ad2a6347b",
            "sha": "f2bb3ec969d6cce2c3ca98f7c2c6e2ed32f19989",
            "subject": "agent: chatgpt-local-reconcile-tomorrow-ff4ad2a6347b"
          },
          {
            "committed_at": 1785337319,
            "ref": "agent/cont-05cc78",
            "sha": "7662fcd8f326bd3e56a08f80aea2c41047f1b965",
            "subject": "fix(security): bake rgba opacity values into gradient to prevent compounding"
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
          }
        ],
        "branches_total": 47,
        "count": 47,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/tomorrow/tomorrow"
      },
      {
        "count": 347,
        "items_digest": "bef820d74d64a3731c4d58ed8804292c86e8d0ec5199881e9d7bf4e0ecb47baf",
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
        "items_total": 347,
        "kind": "orchestrator_rescue_refs",
        "repo": "/Users/kpasch/Documents/tomorrow/tomorrow"
      }
    ]
