PROJECT: beethoven

- id: chatgpt-local-reconcile-beethoven-ee86a2cff698
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
    `ee86a2cff698f1f6b7902e3670e20a536916b2c23e29ca374cfc8711bfebca7d`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "error": "git metadata no longer resolves",
        "kind": "broken_codex_git_worktree",
        "newest_mtime": 1786460086,
        "path": "/Users/kpasch/Documents/Codex/2026-08-07/cons/work/orchestrator-session-fabric"
      },
      {
        "bridge_result_tail": "[chatgpt-bridge] repo=claude-orchestrator root=/Users/kpasch/Documents/beethoven/claude-orchestrator branch=chatgpt/chatgpt-local-queue-bridge-20260811-08111602\n[chatgpt-bridge] default branch: master\n[chatgpt-bridge] committed \u2014 10 file(s) changed\nremote: \nremote: Create a pull request for 'chatgpt/chatgpt-local-queue-bridge-20260811-08111602' on GitHub by visiting:        \nremote:      https://github.com/kalepasch1/claude-orchestrator/pull/new/chatgpt/chatgpt-local-queue-bridge-20260811-08111602        \nremote: \nremote: GitHub found 15 vulnerabilities on kalepasch1/claude-orchestrator's default branch (2 critical, 7 high, 5 moderate, 1 low). To find out more, visit:        \nremote:      https://github.com/kalepasch1/claude-orchestrator/security/dependabot        \nremote: \n[chatgpt-bridge] pushed branch chatgpt/chatgpt-local-queue-bridge-20260811-08111602\n[chatgpt-bridge] PR: https://github.com/kalepasch1/claude-orchestrator/pull/20\nOK: claude-orchestrator \u2014 https://github.com/kalepasch1/claude-orchestrator/pull/20\n",
        "kind": "chatgpt_bridge_artifact",
        "mtime": 1786460509,
        "path": "/Users/kpasch/Documents/chatgpt-dropbox/_applied/20260811-160222--claude-orchestrator--chatgpt-local-queue-bridge-20260811.zip",
        "sha256": "ef8035cb8c47ce437672fed4baed004b2f686b972b1286fd45c0dffdc6e384d6",
        "size": 31499,
        "status": "applied"
      },
      {
        "bridge_result_tail": "[chatgpt-bridge] repo=claude-orchestrator root=/Users/kpasch/Documents/beethoven/claude-orchestrator branch=chatgpt/chatgpt-local-intake-receipt-safety-20260811-08111725\n[chatgpt-bridge] default branch: master\n[chatgpt-bridge] committed \u2014 2 file(s) changed\nremote: \nremote: Create a pull request for 'chatgpt/chatgpt-local-intake-receipt-safety-20260811-08111725' on GitHub by visiting:        \nremote:      https://github.com/kalepasch1/claude-orchestrator/pull/new/chatgpt/chatgpt-local-intake-receipt-safety-20260811-08111725        \nremote: \nremote: GitHub found 15 vulnerabilities on kalepasch1/claude-orchestrator's default branch (2 critical, 7 high, 5 moderate, 1 low). To find out more, visit:        \nremote:      https://github.com/kalepasch1/claude-orchestrator/security/dependabot        \nremote: \n[chatgpt-bridge] pushed branch chatgpt/chatgpt-local-intake-receipt-safety-20260811-08111725\n[chatgpt-bridge] PR: https://github.com/kalepasch1/claude-orchestrator/pull/21\nOK: claude-orchestrator \u2014 https://github.com/kalepasch1/claude-orchestrator/pull/21\n",
        "kind": "chatgpt_bridge_artifact",
        "mtime": 1786465484,
        "path": "/Users/kpasch/Documents/chatgpt-dropbox/_applied/20260811-172514--claude-orchestrator--chatgpt-local-intake-receipt-safety-20260811.zip",
        "sha256": "60033a7351221936d70aa048e2189db1b3381efa055bbb524cc2344eb2518617",
        "size": 14127,
        "status": "applied"
      }
    ]
