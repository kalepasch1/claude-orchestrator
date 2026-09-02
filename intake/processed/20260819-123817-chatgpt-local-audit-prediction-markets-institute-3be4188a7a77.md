PROJECT: prediction-markets-institute

- id: chatgpt-local-reconcile-prediction-markets-institute-3be4188a7a77
  title: Reconcile local ChatGPT/Codex build evidence for prediction-markets-institute
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
    `3be4188a7a77c5d54d0dc7673bede8468ad0194b4493f0c05449cbc5cceea3a7`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "count": 56,
        "items_digest": "7c7dfa1b32a9d816881d65c8fd8393044914dbabe34d2b05f24211313dc08ba3",
        "items_sample": [
          {
            "created_at": 1785684410,
            "ref": "refs/orch-rescue/20260803T000713-pmi",
            "sha": "f51955855676ae936fb31ff9c715ba3b02550ab3",
            "subject": "Merge branch 'agent/relfix-prediction-markets-institute-07301859' (auto-resolved)"
          },
          {
            "created_at": 1785684410,
            "ref": "refs/orch-rescue/20260803T000750-pmi",
            "sha": "f51955855676ae936fb31ff9c715ba3b02550ab3",
            "subject": "Merge branch 'agent/relfix-prediction-markets-institute-07301859' (auto-resolved)"
          },
          {
            "created_at": 1785798781,
            "ref": "refs/orch-rescue/20260803T231301-cc-mutual-default-fund-233c129f",
            "sha": "233c129fe3e575b0012e97e13fa4da16d6f11fe6",
            "subject": "On agent/cc-mutual-default-fund: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785798781,
            "ref": "refs/orch-rescue/20260803T231301-cc-solvency-passport-9905ac82",
            "sha": "9905ac82a14f99397e99e8e9eda081c0db11d1ef",
            "subject": "On agent/cc-solvency-passport: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785798781,
            "ref": "refs/orch-rescue/20260803T231302-convention-conformance-lints-131df9b4",
            "sha": "131df9b4a3714c6d19cf6394af321496f4fefb47",
            "subject": "On agent/convention-conformance-lints: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785938777,
            "ref": "refs/orch-rescue/20260805T140617-pmi-2725f065",
            "sha": "2725f065da8df42e599aafec4590f2d2133decf7",
            "subject": "On main: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785938872,
            "ref": "refs/orch-rescue/20260805T141522-pmi-0715d277",
            "sha": "0715d277de22a078e1adf5a1054f46e38ca3e42a",
            "subject": "feat(pmi): canonical Institute public surface \u2014 think-tank positioning, honest proof, SEO"
          },
          {
            "created_at": 1785944057,
            "ref": "refs/orch-rescue/20260805T153835-pmi-fbb50436",
            "sha": "fbb50436cb7a07c58f32739fd3d81c877bc40be1",
            "subject": "feat(seo): JSON-LD @graph for /research, /data, /fellows, /membership"
          },
          {
            "created_at": 1785947936,
            "ref": "refs/orch-rescue/20260805T163924-pmi-a020181c",
            "sha": "a020181c1171c4f061d227ada6c1d19f747b1d24",
            "subject": "fix(identity): state plainly that PMI is the body and PMA-CICP is its credential"
          },
          {
            "created_at": 1785951455,
            "ref": "refs/orch-rescue/20260805T174047-pmi-8d529ee3",
            "sha": "8d529ee3d38220f5a62179d55e903a62c4f318d0",
            "subject": "feat(seo): publish structured data on the last three public pages"
          },
          {
            "created_at": 1785980977,
            "ref": "refs/orch-rescue/20260806T015732-pmi-f593c632",
            "sha": "f593c6320220baa9e132667d2d6d8bc49e0c310c",
            "subject": "Merge branch 'agent/toolchain-repair-9ac6c067-slice-1' (auto-resolved)"
          },
          {
            "created_at": 1785998860,
            "ref": "refs/orch-rescue/20260806T064740-rework-noop-reroute-model-keys-mock-darwin-live-model-env-gate-e9f7544-dfbc37d1",
            "sha": "dfbc37d13129d1efcd1c1740a6c775259629dfff",
            "subject": "On agent/rework-noop-reroute-model-keys-mock-darwin-live-model-env-gate-e9f7544: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1786020537,
            "ref": "refs/orch-rescue/20260806T124858-pmi-889873eb",
            "sha": "889873eb42f37cf36269f6a2beea96bb2dede2df",
            "subject": "On main: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1786026677,
            "ref": "refs/orch-rescue/20260806T143344-pmi-c6a4fdb6",
            "sha": "c6a4fdb6e4dcdd3eba353339355087e2203da49d",
            "subject": "design(landing): install the shared sister design system"
          },
          {
            "created_at": 1786056723,
            "ref": "refs/orch-rescue/20260806T225203-relfix-racefeed-07060650-fix-typescript-and-build--slice-4-fix-missing-branch-ab185edc",
            "sha": "ab185edcac5e4b5bbb7e9939134fe050df9c4e3c",
            "subject": "On agent/relfix-racefeed-07060650-fix-typescript-and-build--slice-4-fix-missing-branch: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1786056724,
            "ref": "refs/orch-rescue/20260806T225204-rework-buildfail-qafix-pareto-2080-07062319-slice-4-a7288db-088cf079",
            "sha": "088cf07974874981ef3d8f9de96d63bbfeda381f",
            "subject": "On agent/rework-buildfail-qafix-pareto-2080-07062319-slice-4-a7288db: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1786073846,
            "ref": "refs/orch-rescue/20260807T034126-pmi-a39cca5b",
            "sha": "a39cca5b17c456d7fc0c5aa8b0997b310d5990c9",
            "subject": "Merge branch 'agent/toolchain-repair-9ac6c067-slice-3' (auto-resolved)"
          },
          {
            "created_at": 1786151982,
            "ref": "refs/orch-rescue/20260808T011943-factory-unblock-improve-implement-asynchronous-task-processing-3d84bcc0",
            "sha": "3d84bcc09d7e2ab3fb7a71f4da65fecbdf8af41e",
            "subject": "On agent/factory-unblock-improve-implement-asynchronous-task-processing: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1786177098,
            "ref": "refs/orch-rescue/20260808T081818-cade-adversary-tournaments-bc1da627",
            "sha": "bc1da62775cdc6fca44e949d710af1207def4ec5",
            "subject": "On agent/cade-adversary-tournaments: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1786189177,
            "ref": "refs/orch-rescue/20260808T113937-cade-certificate-proof-constitution-f57f1e0e",
            "sha": "f57f1e0ed14eafccf50502d577d2e29a2048acc0",
            "subject": "On agent/cade-certificate-proof-constitution: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1786214934,
            "ref": "refs/orch-rescue/20260808T184854-orch-config-consumption-97cfad6c",
            "sha": "97cfad6c3a9db6350fd94930b4b446654848a390",
            "subject": "On agent/orch-config-consumption: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1786116548,
            "ref": "refs/orch-rescue/20260813T093806-chatgpt-local-reconcile-prediction-markets-institute-f8fdcedbdfc8-f9137af7",
            "sha": "f9137af7755a484a6709a07d6ba0c1fbe83f7d10",
            "subject": "Merge branch 'agent/toolchain-repair-9ac6c067-slice-4' (auto-resolved)"
          },
          {
            "created_at": 1786616154,
            "ref": "refs/orch-rescue/20260813T101554-cade-mirror-negotiation-fd72f608",
            "sha": "fd72f608594f1c906f8c3392dc45bc657bae3866",
            "subject": "On agent/cade-mirror-negotiation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1786652561,
            "ref": "refs/orch-rescue/20260813T202241-cade-mirror-negotiation-0a48825f",
            "sha": "0a48825f2966c430d5e4f90ed67d142eb7135fad",
            "subject": "On agent/cade-mirror-negotiation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1786652562,
            "ref": "refs/orch-rescue/20260813T202242-canary-ollama-2-2-slice-5-cd007ba0",
            "sha": "cd007ba00b1d9b5da95856184aff795e76e37ced",
            "subject": "On agent/canary-ollama-2-2-slice-5: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1786652562,
            "ref": "refs/orch-rescue/20260813T202242-contracts-smarter-0c25d11a",
            "sha": "0c25d11a0a97e47b04371b381e0b80b6687c9bf7",
            "subject": "On agent/contracts-smarter: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1786667880,
            "ref": "refs/orch-rescue/20260814T003800-chatgpt-local-reconcile-prediction-markets-institute-b1a633b1f50b-7a344311",
            "sha": "7a3443119920e1e8c4782f3e80f7778e6f7c2373",
            "subject": "On agent/chatgpt-local-reconcile-prediction-markets-institute-b1a633b1f50b: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1786668270,
            "ref": "refs/orch-rescue/20260814T004431-chatgpt-local-reconcile-prediction-markets-institute-f8fdcedbdfc8-d43a38a2",
            "sha": "d43a38a2fc2c55a3bb97ab9518b0ca1ca342b1bd",
            "subject": "On agent/chatgpt-local-reconcile-prediction-markets-institute-f8fdcedbdfc8: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1786834509,
            "ref": "refs/orch-rescue/20260815T225509-dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-p5-interlock-tests-956921c0",
            "sha": "956921c0b4441f39c0561e1be79820d6160df18d",
            "subject": "On agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-p5-interlock-tests: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1786797406,
            "ref": "refs/orch-rescue/20260817T083338-pmi-b9e35812",
            "sha": "b9e35812386ab3caf30efd5d17c27fb15dd86163",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-prediction-markets-institute-0ec693b8964f' (auto-resolved)"
          }
        ],
        "items_total": 56,
        "kind": "orchestrator_rescue_refs",
        "repo": "/Users/kpasch/Documents/smarter/prediction-markets-institute/pmi"
      }
    ]
