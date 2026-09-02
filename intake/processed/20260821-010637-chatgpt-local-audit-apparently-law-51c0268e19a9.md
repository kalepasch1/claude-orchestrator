PROJECT: apparently-law

- id: chatgpt-local-reconcile-apparently-law-51c0268e19a9
  title: Reconcile local ChatGPT/Codex build evidence for apparently-law
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
    `51c0268e19a9ebe8bae591028682e2e5cc8e71bbefe685e6433e5942940acf9a`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branches": [
          {
            "committed_at": 1785956638,
            "ref": "agent-local/dropbox-apparently-tomorrow-bridge-apparently-law-doc-fabric-prebuil-2-living-embed-capability-critical-dead-simple-t",
            "sha": "f7a0b0bbe89395267eef029d6e72593875918eb7",
            "subject": "agent: dropbox-apparently-tomorrow-bridge-apparently-law-doc-fabric-prebuil-2-living-embed-capability-critical-dead-simple-t"
          },
          {
            "committed_at": 1787042149,
            "ref": "agent/chatgpt-local-reconcile-apparently-law-8361ec1c691b",
            "sha": "074fa1fd1a9b92fedaabbe43ca6c685c267572c9",
            "subject": "agent: chatgpt-local-reconcile-apparently-law-8361ec1c691b"
          },
          {
            "committed_at": 1787042156,
            "ref": "agent/chatgpt-local-reconcile-apparently-law-8f7038514b10",
            "sha": "e6d08d6b732333435d6772044e76cc3e43f7b4c0",
            "subject": "agent: chatgpt-local-reconcile-apparently-law-8f7038514b10"
          },
          {
            "committed_at": 1787042145,
            "ref": "agent/chatgpt-local-reconcile-apparently-law-b04bfeb1cdc4",
            "sha": "9bfc12ca1b77c485f83b195e6cbd7eaf67d6b545",
            "subject": "agent: chatgpt-local-reconcile-apparently-law-b04bfeb1cdc4"
          },
          {
            "committed_at": 1787041947,
            "ref": "agent/chatgpt-local-reconcile-apparently-law-d34eb36efdf6",
            "sha": "e7b35b878f05dd609c8bf9ed4d3591fe3b2ce97c",
            "subject": "agent: chatgpt-local-reconcile-apparently-law-d34eb36efdf6"
          },
          {
            "committed_at": 1787040889,
            "ref": "agent/chatgpt-local-reconcile-apparently-law-db98501abecb",
            "sha": "b012719556e2f8c6aaab5ded88a825f0f1836575",
            "subject": "agent: chatgpt-local-reconcile-apparently-law-db98501abecb"
          },
          {
            "committed_at": 1786973152,
            "ref": "integrate/regmap-final",
            "sha": "3f260d71126b08343a1bdab87eb9aa5b7531d37d",
            "subject": "regulatory map: attorney role gate, candidate import, stylesheet guard"
          },
          {
            "committed_at": 1787177077,
            "ref": "integrate/regmap-sister",
            "sha": "5ead2bac4637487f52b142f6cca8fb6d81bc4c76",
            "subject": "fix(R5): this repo could not rebuild its own schema"
          },
          {
            "committed_at": 1787042156,
            "ref": "orchestrator/dev",
            "sha": "e6d08d6b732333435d6772044e76cc3e43f7b4c0",
            "subject": "agent: chatgpt-local-reconcile-apparently-law-8f7038514b10"
          }
        ],
        "count": 9,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/apparently-law"
      }
    ]
