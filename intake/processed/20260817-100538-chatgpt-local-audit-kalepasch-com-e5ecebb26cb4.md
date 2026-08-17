PROJECT: kalepasch-com

- id: chatgpt-local-reconcile-kalepasch-com-e5ecebb26cb4
  title: Reconcile local ChatGPT/Codex build evidence for kalepasch-com
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
    `e5ecebb26cb4f07d72bec97af462fe2e8e4b45b7185eefc9559776376cc73730`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branches": [
          {
            "committed_at": 1786937943,
            "ref": "agent/chatgpt-local-reconcile-kalepasch-com-6300730f68a8",
            "sha": "4a358a9986f9daffae584a0e63383b984f800cbc",
            "subject": "reconcile(recovery): classify 203 orch-rescue refs, zero UNKNOWN, nothing to recover"
          },
          {
            "committed_at": 1786838511,
            "ref": "agent/chatgpt-local-reconcile-kalepasch-com-d5e24dc69141-slice-1",
            "sha": "7ce4414807bc7f210943d9c07ebbed5914446ff8",
            "subject": "recovery-intent-stub: chatgpt-local-reconcile-kalepasch-com-d5e24dc69141-slice-1"
          },
          {
            "committed_at": 1786835337,
            "ref": "agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-governor-ram-floor",
            "sha": "e2fb57be83dde5c1680e1e13fceddf21791ee006",
            "subject": "Merge self-healed clean files from agent/chatgpt-local-reconcile-kalepasch-com-058b48faa154-slice-1"
          },
          {
            "committed_at": 1786835337,
            "ref": "agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-keepalive-single-supervisor",
            "sha": "e2fb57be83dde5c1680e1e13fceddf21791ee006",
            "subject": "Merge self-healed clean files from agent/chatgpt-local-reconcile-kalepasch-com-058b48faa154-slice-1"
          },
          {
            "committed_at": 1786837753,
            "ref": "agent/orch-config-consumption",
            "sha": "337c238ec2da401167155a5635a258ba4a86e719",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-kalepasch-com-cd566a4ad6ef-slice-1' (auto-resolved)"
          },
          {
            "committed_at": 1785852687,
            "ref": "agent/ploeh-s2s-bridge-tomorrow",
            "sha": "ffa1a2b46704397b824be90c0016863109eedae5",
            "subject": "Merge branch 'agent/relfix-kalepasch-com-ca392a3ba8b4-add-nuxt-dev-dependency-update-tests-checks' (auto-resolved)"
          },
          {
            "committed_at": 1785912101,
            "ref": "agent/prompt-evolution-bandit",
            "sha": "83e7200892b92a7ec2f2e6887ce919a1d99a829c",
            "subject": "Merge branch 'agent/canary-kalepasch-com-20260731' (auto-resolved)"
          },
          {
            "committed_at": 1785853713,
            "ref": "agent/relfix-kalepasch-com-ca392a3ba8b4-add-nuxt-dev-dependency-update-tests-checks",
            "sha": "71cd418ecf86a97fce668d4e681253446d92d534",
            "subject": "salvage: interrupted work for relfix-kalepasch-com-ca392a3ba8b4-add-nuxt-dev-dependency-update-tests-checks"
          },
          {
            "committed_at": 1785971316,
            "ref": "agent/relfix-kalepasch-com-da085f99f2ba-resolve-remaining-conflicts-manually",
            "sha": "08b29db7ad7df2665df59d61ec352cd40839b915",
            "subject": "salvage: interrupted work for relfix-kalepasch-com-da085f99f2ba-resolve-remaining-conflicts-manually"
          },
          {
            "committed_at": 1786837753,
            "ref": "main",
            "sha": "337c238ec2da401167155a5635a258ba4a86e719",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-kalepasch-com-cd566a4ad6ef-slice-1' (auto-resolved)"
          },
          {
            "committed_at": 1784761526,
            "ref": "safety/pre-canonical-deploy-20260722",
            "sha": "d3ec59f2bfbe5d42e7564404507a61b8e2222265",
            "subject": "Merge remote-tracking branch 'origin/main'"
          }
        ],
        "count": 11,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/smarter/pasch"
      }
    ]
