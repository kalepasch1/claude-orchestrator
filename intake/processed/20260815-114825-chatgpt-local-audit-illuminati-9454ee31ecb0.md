PROJECT: illuminati

- id: chatgpt-local-reconcile-illuminati-9454ee31ecb0
  title: Reconcile local ChatGPT/Codex build evidence for illuminati
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
    `9454ee31ecb00f1a865f794957fdaea611d962df76ddc3018e316350dce93578`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "agent/cade-mirror-negotiation",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "a855370fad03292a771700416601db0e0f87f127",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786741647,
        "path": "/Users/kpasch/Documents/illuminati-wt/cade-mirror-negotiation"
      },
      {
        "branch": "agent/canary-ollama-2-2-slice-5",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "2e43ac5e4df3e65ffc9bc847aa745f2ce0e9c38d",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786741704,
        "path": "/Users/kpasch/Documents/illuminati-wt/canary-ollama-2-2-slice-5"
      },
      {
        "branch": "agent/contracts-smarter",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "d40cd535e6faf284501169470c705463e77b9569",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786741639,
        "path": "/Users/kpasch/Documents/illuminati-wt/contracts-smarter"
      },
      {
        "branch": "agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-env-key-disable",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "2e43ac5e4df3e65ffc9bc847aa745f2ce0e9c38d",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786741691,
        "path": "/Users/kpasch/Documents/illuminati-wt/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-env-key-disable"
      },
      {
        "branch": "agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-p4-deploy-kpi",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "2e43ac5e4df3e65ffc9bc847aa745f2ce0e9c38d",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786741694,
        "path": "/Users/kpasch/Documents/illuminati-wt/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-p4-deploy-kpi"
      },
      {
        "branch": "agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-p5-interlock-tests",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "2e43ac5e4df3e65ffc9bc847aa745f2ce0e9c38d",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786741700,
        "path": "/Users/kpasch/Documents/illuminati-wt/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-p5-interlock-tests"
      },
      {
        "branch": "agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-p5-pause-arbiter",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "2e43ac5e4df3e65ffc9bc847aa745f2ce0e9c38d",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786741697,
        "path": "/Users/kpasch/Documents/illuminati-wt/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-p5-pause-arbiter"
      },
      {
        "branch": "agent/orch-cross-project-depends",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "ad3cc5f7aafd9687eb495b37291714cc5915706a",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786741656,
        "path": "/Users/kpasch/Documents/illuminati-wt/orch-cross-project-depends"
      },
      {
        "branch": "agent/relfix-racefeed-07060650-fix-typescript-and-build--slice-4-fix-missing-branch",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "2e43ac5e4df3e65ffc9bc847aa745f2ce0e9c38d",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786741687,
        "path": "/Users/kpasch/Documents/illuminati-wt/relfix-racefeed-07060650-fix-typescript-and-build--slice-4-fix-missing-branch"
      },
      {
        "branch": "agent/rework-buildfail-qafix-pareto-2080-07062319-slice-4-a7288db",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "2e43ac5e4df3e65ffc9bc847aa745f2ce0e9c38d",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786741673,
        "path": "/Users/kpasch/Documents/illuminati-wt/rework-buildfail-qafix-pareto-2080-07062319-slice-4-a7288db"
      },
      {
        "branch": "agent/rework-noop-relfix-racefeed-07060650-install-fetch-nodeshim-f3f967c",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "2e43ac5e4df3e65ffc9bc847aa745f2ce0e9c38d",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786741667,
        "path": "/Users/kpasch/Documents/illuminati-wt/rework-noop-relfix-racefeed-07060650-install-fetch-nodeshim-f3f967c"
      },
      {
        "branch": "agent/rework-noop-reroute-model-keys-mock-darwin-live-model-env-gate-e9f7544",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "2e43ac5e4df3e65ffc9bc847aa745f2ce0e9c38d",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786741670,
        "path": "/Users/kpasch/Documents/illuminati-wt/rework-noop-reroute-model-keys-mock-darwin-live-model-env-gate-e9f7544"
      },
      {
        "branch": "agent/rework-oversized-relfix-racefeed-07060650-sub-task-4-report-failure-if-n-5cfe75f",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "82d928470829c25e875ae370c66642a7a99febf8",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786741663,
        "path": "/Users/kpasch/Documents/illuminati-wt/rework-oversized-relfix-racefeed-07060650-sub-task-4-report-failure-if-n-5cfe75f"
      },
      {
        "branch": "agent/session-proof-of-work",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "d40cd535e6faf284501169470c705463e77b9569",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786741652,
        "path": "/Users/kpasch/Documents/illuminati-wt/session-proof-of-work"
      },
      {
        "branch": "agent/smarter-5-95",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "a855370fad03292a771700416601db0e0f87f127",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786741644,
        "path": "/Users/kpasch/Documents/illuminati-wt/smarter-5-95"
      },
      {
        "branches": [
          {
            "committed_at": 1786491670,
            "ref": "codex/trojun-canonical-rename",
            "sha": "b4769b8eeb5e7be26d84f5de011b1baa08ddb2ae",
            "subject": "Rename Illuminati application to Trojun"
          }
        ],
        "count": 1,
        "kind": "unmerged_chatgpt_codex_branches",
        "repo": "/Users/kpasch/Documents/Trojun"
      },
      {
        "branches": [
          {
            "committed_at": 1785182261,
            "ref": "chatgpt/post-hardening-selftest-07271457",
            "sha": "13f7b62bb4531015f9641dce1e1eaa856278ffbe",
            "subject": "chore: post-hardening bridge selftest"
          }
        ],
        "count": 1,
        "kind": "unmerged_chatgpt_codex_branches",
        "repo": "/Users/kpasch/Documents/illuminati"
      },
      {
        "kind": "unregistered_local_repo",
        "note": "repo is not present in runner/deployment_bindings.json; verify canonical ownership",
        "path": "/Users/kpasch/Documents/Trojun",
        "routing": "illuminati"
      },
      {
        "kind": "unregistered_local_repo",
        "note": "repo is not present in runner/deployment_bindings.json; verify canonical ownership",
        "path": "/Users/kpasch/Documents/_Trojun_archived",
        "routing": "illuminati"
      }
    ]
