PROJECT: vigil

- id: chatgpt-local-reconcile-vigil-4d34f533c156
  title: Reconcile local ChatGPT/Codex build evidence for vigil
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
    `4d34f533c1567f9da4312b079cbe8651f246dd068b96bdf7b1544bf82883db11`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "count": 49,
        "items_digest": "3c3206590b427bda34f81db6af35947f4fa5f255e329ea4d9c14f359ad2d8e67",
        "items_sample": [
          {
            "created_at": 1785594280,
            "ref": "refs/orch-rescue/20260803T000633-cc-mutual-default-fund",
            "sha": "424a084ff5709f3638db790369e38aee4b2e3575",
            "subject": "Merge branch 'agent/weekly-lint-vigil' (auto-resolved)"
          },
          {
            "created_at": 1785594280,
            "ref": "refs/orch-rescue/20260803T000633-economic-scheduler-revenue",
            "sha": "424a084ff5709f3638db790369e38aee4b2e3575",
            "subject": "Merge branch 'agent/weekly-lint-vigil' (auto-resolved)"
          },
          {
            "created_at": 1785697756,
            "ref": "refs/orch-rescue/20260803T000633-vigil",
            "sha": "91b492289594bbfed8a831f0160dadfdffaf8b65",
            "subject": "Merge branch 'agent/weekly-lint-vigil-add-lint-notification' (auto-resolved)"
          },
          {
            "created_at": 1785594280,
            "ref": "refs/orch-rescue/20260803T000634-merged-diff-memory",
            "sha": "424a084ff5709f3638db790369e38aee4b2e3575",
            "subject": "Merge branch 'agent/weekly-lint-vigil' (auto-resolved)"
          },
          {
            "created_at": 1785594280,
            "ref": "refs/orch-rescue/20260803T000634-ploeh-s2s-bridge-tomorrow",
            "sha": "424a084ff5709f3638db790369e38aee4b2e3575",
            "subject": "Merge branch 'agent/weekly-lint-vigil' (auto-resolved)"
          },
          {
            "created_at": 1785594280,
            "ref": "refs/orch-rescue/20260803T000634-prompt-evolution-bandit",
            "sha": "424a084ff5709f3638db790369e38aee4b2e3575",
            "subject": "Merge branch 'agent/weekly-lint-vigil' (auto-resolved)"
          },
          {
            "created_at": 1785697756,
            "ref": "refs/orch-rescue/20260803T000734-vigil",
            "sha": "91b492289594bbfed8a831f0160dadfdffaf8b65",
            "subject": "Merge branch 'agent/weekly-lint-vigil-add-lint-notification' (auto-resolved)"
          },
          {
            "created_at": 1785594280,
            "ref": "refs/orch-rescue/20260803T000735-cc-mutual-default-fund",
            "sha": "424a084ff5709f3638db790369e38aee4b2e3575",
            "subject": "Merge branch 'agent/weekly-lint-vigil' (auto-resolved)"
          },
          {
            "created_at": 1785594280,
            "ref": "refs/orch-rescue/20260803T000735-economic-scheduler-revenue",
            "sha": "424a084ff5709f3638db790369e38aee4b2e3575",
            "subject": "Merge branch 'agent/weekly-lint-vigil' (auto-resolved)"
          },
          {
            "created_at": 1785594280,
            "ref": "refs/orch-rescue/20260803T000735-merged-diff-memory",
            "sha": "424a084ff5709f3638db790369e38aee4b2e3575",
            "subject": "Merge branch 'agent/weekly-lint-vigil' (auto-resolved)"
          },
          {
            "created_at": 1785594280,
            "ref": "refs/orch-rescue/20260803T000735-ploeh-s2s-bridge-tomorrow",
            "sha": "424a084ff5709f3638db790369e38aee4b2e3575",
            "subject": "Merge branch 'agent/weekly-lint-vigil' (auto-resolved)"
          },
          {
            "created_at": 1785594280,
            "ref": "refs/orch-rescue/20260803T000735-prompt-evolution-bandit",
            "sha": "424a084ff5709f3638db790369e38aee4b2e3575",
            "subject": "Merge branch 'agent/weekly-lint-vigil' (auto-resolved)"
          },
          {
            "created_at": 1785594280,
            "ref": "refs/orch-rescue/20260803T001455-cc-mutual-default-fund-424a084f",
            "sha": "424a084ff5709f3638db790369e38aee4b2e3575",
            "subject": "Merge branch 'agent/weekly-lint-vigil' (auto-resolved)"
          },
          {
            "created_at": 1785594280,
            "ref": "refs/orch-rescue/20260803T001455-economic-scheduler-revenue-424a084f",
            "sha": "424a084ff5709f3638db790369e38aee4b2e3575",
            "subject": "Merge branch 'agent/weekly-lint-vigil' (auto-resolved)"
          },
          {
            "created_at": 1785594280,
            "ref": "refs/orch-rescue/20260803T001455-merged-diff-memory-424a084f",
            "sha": "424a084ff5709f3638db790369e38aee4b2e3575",
            "subject": "Merge branch 'agent/weekly-lint-vigil' (auto-resolved)"
          },
          {
            "created_at": 1785594280,
            "ref": "refs/orch-rescue/20260803T001455-ploeh-s2s-bridge-tomorrow-424a084f",
            "sha": "424a084ff5709f3638db790369e38aee4b2e3575",
            "subject": "Merge branch 'agent/weekly-lint-vigil' (auto-resolved)"
          },
          {
            "created_at": 1785594280,
            "ref": "refs/orch-rescue/20260803T001455-prompt-evolution-bandit-424a084f",
            "sha": "424a084ff5709f3638db790369e38aee4b2e3575",
            "subject": "Merge branch 'agent/weekly-lint-vigil' (auto-resolved)"
          },
          {
            "created_at": 1785726172,
            "ref": "refs/orch-rescue/20260803T030252-breach-remediation-6847c6f4",
            "sha": "6847c6f42ce650d86f273626e3238f004ef89899",
            "subject": "On agent/breach-remediation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785818506,
            "ref": "refs/orch-rescue/20260804T044146-canary-vigil-20260727-add-update-tests-54856f00",
            "sha": "54856f009775ba7c9ad205c494c08d4ce51c523e",
            "subject": "On agent/canary-vigil-20260727-add-update-tests: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785818767,
            "ref": "refs/orch-rescue/20260804T044607-canary-vigil-20260727-add-update-tests-86bcf033",
            "sha": "86bcf03337e1e5a0c46e3344d501678037bf2dcf",
            "subject": "On agent/canary-vigil-20260727-add-update-tests: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785819435,
            "ref": "refs/orch-rescue/20260804T045716-canary-vigil-20260727-add-update-tests-68be2d56",
            "sha": "68be2d56aac474c541960abe06e0fc345a925a78",
            "subject": "On agent/canary-vigil-20260727-add-update-tests: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785819690,
            "ref": "refs/orch-rescue/20260804T050130-canary-vigil-20260727-add-update-tests-4daed16a",
            "sha": "4daed16a944a7211e50dce2e16ea1495e60d3513",
            "subject": "On agent/canary-vigil-20260727-add-update-tests: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785819986,
            "ref": "refs/orch-rescue/20260804T050626-canary-vigil-20260727-add-update-tests-251e8ff8",
            "sha": "251e8ff8ba9bbb6b825398366b0e6f34de009148",
            "subject": "On agent/canary-vigil-20260727-add-update-tests: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785820701,
            "ref": "refs/orch-rescue/20260804T051821-canary-vigil-20260730-a91a43a1",
            "sha": "a91a43a104cad9a5120d4d0a606089e652c967e8",
            "subject": "On agent/canary-vigil-20260730: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785847286,
            "ref": "refs/orch-rescue/20260804T133401-vigil-0e2ed289",
            "sha": "0e2ed289feae4267ca7e444158bf9642fc44d3eb",
            "subject": "fix(cron): raise Vercel function memory to 3009 MB for agentic-tests OOM"
          },
          {
            "created_at": 1785853410,
            "ref": "refs/orch-rescue/20260804T142755-vigil-25be4ba3",
            "sha": "25be4ba313f16961c6c80524694d1343bdd11c67",
            "subject": "Merge branch 'agent/relfix-vigil-07291153' (auto-resolved)"
          },
          {
            "created_at": 1785908276,
            "ref": "refs/orch-rescue/20260805T053756-pinned-express-lane-e4b3112e",
            "sha": "e4b3112ebce76079ad27be822d54fcd85e92124e",
            "subject": "On agent/pinned-express-lane: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785908276,
            "ref": "refs/orch-rescue/20260805T053757-ploeh-s2s-bridge-tomorrow-20ad0e48",
            "sha": "20ad0e48b4b30b5fa02fc0b334767eecca2988c8",
            "subject": "On agent/ploeh-s2s-bridge-tomorrow: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785908277,
            "ref": "refs/orch-rescue/20260805T053758-prompt-evolution-bandit-bbdc6af8",
            "sha": "bbdc6af8c1c805ce02aa481b366b05124ab0ab18",
            "subject": "On agent/prompt-evolution-bandit: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785908278,
            "ref": "refs/orch-rescue/20260805T053758-smarter-5-95-7f5d44a2",
            "sha": "7f5d44a26e870cd3ee3f0aaa14f6d6627cce365a",
            "subject": "On agent/smarter-5-95: orch-rescue: periodic sweep"
          }
        ],
        "items_total": 49,
        "kind": "orchestrator_rescue_refs",
        "repo": "/Users/kpasch/Documents/vigil"
      }
    ]
