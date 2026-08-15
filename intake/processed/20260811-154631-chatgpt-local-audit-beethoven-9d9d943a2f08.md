PROJECT: beethoven

- id: chatgpt-local-reconcile-beethoven-9d9d943a2f08
  title: Reconcile local ChatGPT/Codex build evidence for beethoven
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
    `9d9d943a2f08af3bc8413098078d1d3f7127a60712bd5ebf9957cd43668a553c`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "bridge_result_tail": "[chatgpt-bridge] repo=claude-orchestrator root=/Users/kpasch/Documents/beethoven/claude-orchestrator branch=chatgpt/chatgpt-local-queue-bridge-20260811-08111602\n[chatgpt-bridge] default branch: master\n[chatgpt-bridge] committed \u2014 10 file(s) changed\nremote: \nremote: Create a pull request for 'chatgpt/chatgpt-local-queue-bridge-20260811-08111602' on GitHub by visiting:        \nremote:      https://github.com/kalepasch1/claude-orchestrator/pull/new/chatgpt/chatgpt-local-queue-bridge-20260811-08111602        \nremote: \nremote: GitHub found 15 vulnerabilities on kalepasch1/claude-orchestrator's default branch (2 critical, 7 high, 5 moderate, 1 low). To find out more, visit:        \nremote:      https://github.com/kalepasch1/claude-orchestrator/security/dependabot        \nremote: \n[chatgpt-bridge] pushed branch chatgpt/chatgpt-local-queue-bridge-20260811-08111602\n[chatgpt-bridge] PR: https://github.com/kalepasch1/claude-orchestrator/pull/20\nOK: claude-orchestrator \u2014 https://github.com/kalepasch1/claude-orchestrator/pull/20\n",
        "kind": "chatgpt_bridge_artifact",
        "mtime": 1786460509,
        "path": "/Users/kpasch/Documents/chatgpt-dropbox/_applied/20260811-160222--claude-orchestrator--chatgpt-local-queue-bridge-20260811.zip",
        "sha256": "ef8035cb8c47ce437672fed4baed004b2f686b972b1286fd45c0dffdc6e384d6",
        "size": 31499,
        "status": "applied"
      }
    ]
