PROJECT: prediction-markets-institute

- id: chatgpt-local-reconcile-prediction-markets-institute-3624c900337c
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
    `3624c900337ce539cb4545f95df454296559320f4bcf36b7eac6be4ca513c6b1`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branches": [
          {
            "committed_at": 1787067416,
            "ref": "agent/backlog-batch-prediction-markets-institute-349a57f",
            "sha": "b8eb5704e16430d350067ec59aad33e0f457bb35",
            "subject": "recovery-intent-stub: backlog-batch-prediction-markets-institute-349a57f"
          },
          {
            "committed_at": 1787086873,
            "ref": "agent/relfix-prediction-markets-institute-015581bc1163-fix-done-patch-to-auto-populate-clean-086872",
            "sha": "1a10a06d0a80c5188e9b57b36a9fb17d85e6ed26",
            "subject": "self-heal: clean files from agent/relfix-prediction-markets-institute-015581bc1163-fix-done-patch-to-auto-populate (7 files)"
          },
          {
            "committed_at": 1787082344,
            "ref": "agent/relfix-prediction-markets-institute-07301859",
            "sha": "9faa9708f1dcd9cb4971d8bb7265ad0ba522d48a",
            "subject": "Add npm test: pin the publications no-proof guard with dependency-free unit tests"
          },
          {
            "committed_at": 1787086849,
            "ref": "agent/relfix-v15-predictions-766973c7",
            "sha": "17d88801b3f7db3de7d6d3badf15d7ee83be7019",
            "subject": "salvage: interrupted work for relfix-v15-predictions-766973c7"
          },
          {
            "committed_at": 1785679679,
            "ref": "agent/shadow-facc0b03-cowork",
            "sha": "fd982fd818974048497b393f64220540e9b44bc6",
            "subject": "recovery-intent-stub: shadow-facc0b03-cowork"
          },
          {
            "committed_at": 1785682756,
            "ref": "agent/shadow-facc0b03-orchestrator_native",
            "sha": "002924d648e5a2eebd65b85129d02306aa60cb75",
            "subject": "recovery-intent-stub: shadow-facc0b03-orchestrator_native"
          },
          {
            "committed_at": 1787083233,
            "ref": "backup/relfix-015581bc1163-pre-rebuild",
            "sha": "03607e7160d456e55fcdc2a192bd77013e66b380",
            "subject": "Auto-populate artifact_commit when closing tasks as DONE"
          }
        ],
        "count": 7,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/smarter/prediction-markets-institute/pmi"
      }
    ]
