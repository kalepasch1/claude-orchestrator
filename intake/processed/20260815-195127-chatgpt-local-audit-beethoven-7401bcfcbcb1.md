PROJECT: beethoven

- id: chatgpt-local-reconcile-beethoven-7401bcfcbcb1
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
    `7401bcfcbcb1b8b6461349d08ed488feda231ba325981cd77b1685f1f069beb2`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "count": 493,
        "items_digest": "86f1b445329d60f1f2cae8e3d43884f26679137c293dc6a05374ccd1a34f9a14",
        "items_sample": [
          {
            "created_at": 1785715636,
            "ref": "refs/orch-rescue/20260803T000716-claude-orchestrator",
            "sha": "685bec47743acd2a3a650e4c7f9292b8da075ef6",
            "subject": "On master: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715638,
            "ref": "refs/orch-rescue/20260803T000718-breach-remediation",
            "sha": "72bc7ddf1f86a063743b4580974bad1edd05773e",
            "subject": "On agent/breach-remediation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715639,
            "ref": "refs/orch-rescue/20260803T000719-cade-mirror-negotiation",
            "sha": "696872815d7128b21fb39251cb0dcdf24f766b14",
            "subject": "On agent/cade-mirror-negotiation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715640,
            "ref": "refs/orch-rescue/20260803T000720-cc-legacy-margin-removal",
            "sha": "c3d1aa9ea875f4dce9cda820a56c07e55df4aaf4",
            "subject": "On agent/cc-legacy-margin-removal: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715641,
            "ref": "refs/orch-rescue/20260803T000721-cc-mutual-default-fund",
            "sha": "54cb2405c801e47bbd126a557b3493a7463f20ce",
            "subject": "On agent/cc-mutual-default-fund: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715641,
            "ref": "refs/orch-rescue/20260803T000721-cc-solvency-passport",
            "sha": "cb458638f92ba1b17d86374a7a5961218fa7c224",
            "subject": "On agent/cc-solvency-passport: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715642,
            "ref": "refs/orch-rescue/20260803T000722-convention-conformance-lints",
            "sha": "7530399a51075888d1cbc54c2e5ff897861339e6",
            "subject": "On agent/convention-conformance-lints: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715643,
            "ref": "refs/orch-rescue/20260803T000723-economic-scheduler-revenue",
            "sha": "c23fdeee475de01cec3dd8ec5a4e5e4707ddbfd1",
            "subject": "On agent/economic-scheduler-revenue: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715644,
            "ref": "refs/orch-rescue/20260803T000724-ext-streaming-terms",
            "sha": "93d532b1c586551809cbba6fe4f035a30ae358bb",
            "subject": "On agent/ext-streaming-terms: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715644,
            "ref": "refs/orch-rescue/20260803T000724-hive-enforcement-velocity-index",
            "sha": "62602aee6fc65c27dc908f8cb07f456ba986f4c9",
            "subject": "On agent/hive-enforcement-velocity-index: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715644,
            "ref": "refs/orch-rescue/20260803T000724-merged-diff-memory",
            "sha": "791ce633eed2c06eb9ad96761c0d011e12e5ad4a",
            "subject": "On agent/merged-diff-memory: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715645,
            "ref": "refs/orch-rescue/20260803T000725-oc-autoclear-policy",
            "sha": "4202f5b49f2d8b000f169405afd22f90aef70fee",
            "subject": "On agent/oc-autoclear-policy: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715645,
            "ref": "refs/orch-rescue/20260803T000725-orch-config-consumption",
            "sha": "0bee7ff2f1f351dfbe792245978ccd61a70ce238",
            "subject": "On agent/orch-config-consumption: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715645,
            "ref": "refs/orch-rescue/20260803T000725-pinned-express-lane",
            "sha": "5f3ed25ef56f6cf9eed2cff816e69bf310dd1d62",
            "subject": "On agent/pinned-express-lane: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715645,
            "ref": "refs/orch-rescue/20260803T000725-ploeh-s2s-bridge-tomorrow",
            "sha": "17646f8e58bcc9b86e77bfd282d0bf6dd0fe9efe",
            "subject": "On agent/ploeh-s2s-bridge-tomorrow: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715646,
            "ref": "refs/orch-rescue/20260803T000726-prompt-evolution-bandit",
            "sha": "c724ed32431eeaac9d26c743e5ba0f4892347e7c",
            "subject": "On agent/prompt-evolution-bandit: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715646,
            "ref": "refs/orch-rescue/20260803T000726-relfix-racefeed-07060650-slice-4",
            "sha": "9c023d06b7446d5d97e539979a17e47af66415cb",
            "subject": "On fix-branch: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715671,
            "ref": "refs/orch-rescue/20260803T000751-breach-remediation",
            "sha": "1ae53af0304da13115a858c5607694cfb32766c8",
            "subject": "On agent/breach-remediation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715671,
            "ref": "refs/orch-rescue/20260803T000751-cade-mirror-negotiation",
            "sha": "730ac4d5e6b5e53339572abd4b91077d577e197b",
            "subject": "On agent/cade-mirror-negotiation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715671,
            "ref": "refs/orch-rescue/20260803T000751-cc-legacy-margin-removal",
            "sha": "eb0f0cb53cb34c4fef57810a6008feeaf9b85b29",
            "subject": "On agent/cc-legacy-margin-removal: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715671,
            "ref": "refs/orch-rescue/20260803T000751-cc-mutual-default-fund",
            "sha": "ef9819ce0821ec013c54c9f1cfcab52fe775aa8e",
            "subject": "On agent/cc-mutual-default-fund: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715671,
            "ref": "refs/orch-rescue/20260803T000751-cc-solvency-passport",
            "sha": "f87dd5880750cec7466c87ac4e3d359333218d5e",
            "subject": "On agent/cc-solvency-passport: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715671,
            "ref": "refs/orch-rescue/20260803T000751-claude-orchestrator",
            "sha": "297045a4747551df5dc2c6b7a808782ec162b940",
            "subject": "On master: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715671,
            "ref": "refs/orch-rescue/20260803T000751-convention-conformance-lints",
            "sha": "e4939832797b20ae7a32ea5286eca04cfc717c35",
            "subject": "On agent/convention-conformance-lints: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715671,
            "ref": "refs/orch-rescue/20260803T000751-economic-scheduler-revenue",
            "sha": "4b70e54e5e84d811e0ea757cc30145b55fa8c90d",
            "subject": "On agent/economic-scheduler-revenue: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715672,
            "ref": "refs/orch-rescue/20260803T000752-ext-streaming-terms",
            "sha": "1a057825f68bdbee67f2d25267c09be86fbf6374",
            "subject": "On agent/ext-streaming-terms: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715672,
            "ref": "refs/orch-rescue/20260803T000752-hive-enforcement-velocity-index",
            "sha": "c9f3f13cb65d42652b97e9acf8fc14fc49722866",
            "subject": "On agent/hive-enforcement-velocity-index: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715672,
            "ref": "refs/orch-rescue/20260803T000752-merged-diff-memory",
            "sha": "6224b1d8130f62992bc7cd2f721d7ef57f843b9c",
            "subject": "On agent/merged-diff-memory: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715672,
            "ref": "refs/orch-rescue/20260803T000752-oc-autoclear-policy",
            "sha": "925cb1cb72c51d8a8f873f18594ffcb9a448adda",
            "subject": "On agent/oc-autoclear-policy: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715672,
            "ref": "refs/orch-rescue/20260803T000752-orch-config-consumption",
            "sha": "8e413e3adb3c0a79d7bf19953aac661c094e2f46",
            "subject": "On agent/orch-config-consumption: orch-rescue: periodic sweep"
          }
        ],
        "items_total": 493,
        "kind": "orchestrator_rescue_refs",
        "repo": "/Users/kpasch/Documents/beethoven/claude-orchestrator"
      },
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
      }
    ]
