PROJECT: pareto-2080

- id: chatgpt-local-reconcile-pareto-2080-666dc7a62a3c
  title: Reconcile local ChatGPT/Codex build evidence for pareto-2080
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
    `666dc7a62a3cf658be10519c77381c2a0295a60a9fbfa6c1f127e1eb68059121`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branches": [
          {
            "committed_at": 1786829120,
            "ref": "agent/contracts-smarter",
            "sha": "91f562a854c5b37eaedb24aa6589267becbf7974",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-pareto-2080-005d8278c39c' (auto-resolved)"
          },
          {
            "committed_at": 1786829120,
            "ref": "agent/prompt-evolution-bandit",
            "sha": "91f562a854c5b37eaedb24aa6589267becbf7974",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-pareto-2080-005d8278c39c' (auto-resolved)"
          },
          {
            "committed_at": 1786672998,
            "ref": "agent/recover-missing-branch-qafix-pareto-2080-07062319-slice-1-slice-4-inspect-local-branches",
            "sha": "9a88a84e66826b6b05a5c33b6a60b79f2306d0bd",
            "subject": "build: dedupe vue via npm overrides to fix Nitro trace recursion"
          },
          {
            "committed_at": 1786832087,
            "ref": "agent/recover-missing-branch-toolchain-repair-6096aa2b-fix-node-modules-install-slice-2",
            "sha": "b49c9ca93ffa78d0c7c121a08b10ddce0ee23cb9",
            "subject": "agent: recover-missing-branch-toolchain-repair-6096aa2b-fix-node-modules-install-slice-2"
          },
          {
            "committed_at": 1786829120,
            "ref": "agent/smarter-5-95",
            "sha": "91f562a854c5b37eaedb24aa6589267becbf7974",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-pareto-2080-005d8278c39c' (auto-resolved)"
          }
        ],
        "count": 5,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/pareto/2080"
      }
    ]
