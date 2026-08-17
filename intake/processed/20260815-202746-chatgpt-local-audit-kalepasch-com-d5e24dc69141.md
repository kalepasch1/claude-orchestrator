PROJECT: kalepasch-com

- id: chatgpt-local-reconcile-kalepasch-com-d5e24dc69141
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
    `d5e24dc691416ad28943844c7f3a10ba92e8b2954f452cbad31bf718cbd934b9`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branches": [
          {
            "committed_at": 1786802143,
            "ref": "agent/chatgpt-local-reconcile-kalepasch-com-058b48faa154",
            "sha": "7ee53bcfee8bf1a7c4bd4d1af6d3aeacee4c9862",
            "subject": "recovery-intent-stub: chatgpt-local-reconcile-kalepasch-com-058b48faa154"
          },
          {
            "committed_at": 1786802355,
            "ref": "agent/chatgpt-local-reconcile-kalepasch-com-b61040aea849",
            "sha": "d5c1b1b0bff535405b51e4db4fcddc0519d4a762",
            "subject": "recovery-intent-stub: chatgpt-local-reconcile-kalepasch-com-b61040aea849"
          },
          {
            "committed_at": 1786802534,
            "ref": "agent/chatgpt-local-reconcile-kalepasch-com-bc0e208ad8e3",
            "sha": "b3fe48dbe0f073d76509cb45a9947f6dcdb11673",
            "subject": "recovery-intent-stub: chatgpt-local-reconcile-kalepasch-com-bc0e208ad8e3"
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
            "committed_at": 1784761526,
            "ref": "safety/pre-canonical-deploy-20260722",
            "sha": "d3ec59f2bfbe5d42e7564404507a61b8e2222265",
            "subject": "Merge remote-tracking branch 'origin/main'"
          }
        ],
        "count": 8,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/smarter/pasch"
      }
    ]
