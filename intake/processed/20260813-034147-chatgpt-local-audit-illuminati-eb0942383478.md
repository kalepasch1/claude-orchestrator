PROJECT: illuminati

- id: chatgpt-local-reconcile-illuminati-eb0942383478
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
    `eb09423834781caaa35605b6ff51396b7aadf5419a7d83f048be762976019d2e`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branches_digest": "ba01960248797b8df16f5929db92a74054066cb7b4a468750e6ea2abc8e2d263",
        "branches_sample": [
          {
            "committed_at": 1786076753,
            "ref": "agent/backlog-batch-illuminati-d3ba8c6-weekly-lint-fix-lint-and-typecheck-fix-lint-and",
            "sha": "b1e009544bfa1b6c47096bdc47094272654174d3",
            "subject": "regen-from-cache(template): backlog-batch-illuminati-d3ba8c6-weekly-lint-fix-lint-and-typecheck-fix-lint-and"
          },
          {
            "committed_at": 1785963949,
            "ref": "agent/backlog-batch-illuminati-d3ba8c6-weekly-lint-fix-typechec",
            "sha": "8de7c7ba8891f83dcc5748c2e547152e9a475d7c",
            "subject": "recovery-intent-stub: recover-missing-branch-backlog-batch-illuminati-d3ba8c6-weekly-lint-fix-typechec"
          },
          {
            "committed_at": 1784951522,
            "ref": "agent/backlog-batch-illuminati-dd47b58",
            "sha": "80351380fe5b6765a9aab1b2d680dde2049c362b",
            "subject": "agent: backlog-batch-illuminati-dd47b58"
          },
          {
            "committed_at": 1785895886,
            "ref": "agent/backlog-batch-illuminati-dd47b58-apply-patch-template",
            "sha": "72161a82ebfac9ef205579fec550813e1c94b9d2",
            "subject": "regen-from-cache(template): backlog-batch-illuminati-dd47b58-apply-patch-template"
          },
          {
            "committed_at": 1785897647,
            "ref": "agent/backlog-batch-illuminati-dd47b58-patch-template",
            "sha": "41e82f8ad412caf59a04fac1a68d189d8aceb5d7",
            "subject": "regen-from-cache(template): backlog-batch-illuminati-dd47b58-patch-template"
          },
          {
            "committed_at": 1785944835,
            "ref": "agent/backlog-batch-illuminati-dd47b58-remove-duplicate-pricinggridreconstructi",
            "sha": "e00a315c78d50671014481931bc5e36e05e3e01f",
            "subject": "regen-from-cache(template): backlog-batch-illuminati-dd47b58-remove-duplicate-pricinggridreconstructi"
          },
          {
            "committed_at": 1786121882,
            "ref": "agent/divergent-illuminati-union-merge-symbol-loss-exitsemantic",
            "sha": "4dec422a18aad6ddf865488407f9d25be37ab80f",
            "subject": "regen-from-cache(template): divergent-illuminati-union-merge-symbol-loss-exitsemantic"
          },
          {
            "committed_at": 1786026386,
            "ref": "agent/dropbox-apparently-one-apparently-illuminati-unification-capability--escalation-",
            "sha": "6baa25d7f7abb599281f79ea15f5c74d52e9b8e0",
            "subject": "agent: dropbox-apparently-one-apparently-illuminati-unification-capability--escalation-"
          },
          {
            "committed_at": 1786024813,
            "ref": "agent/dropbox-beethoven-core-integrity-audit-merge-safety-self-protection--group-5",
            "sha": "0d6f299650d0564c98dbdc338a076a5c4526cdf6",
            "subject": "agent: dropbox-beethoven-core-integrity-audit-merge-safety-self-protection--group-5"
          },
          {
            "committed_at": 1785989364,
            "ref": "agent/dropbox-cross-app-hivemind-federation-one-market-s-slice-1",
            "sha": "0377c338f724e8469475bd80170689ada36f230d",
            "subject": "agent: federation 50-500X extensions (a-d), all four"
          },
          {
            "committed_at": 1785989364,
            "ref": "agent/dropbox-cross-app-hivemind-federation-one-market-s-slice-3",
            "sha": "0377c338f724e8469475bd80170689ada36f230d",
            "subject": "agent: federation 50-500X extensions (a-d), all four"
          },
          {
            "committed_at": 1785989364,
            "ref": "agent/dropbox-cross-app-hivemind-federation-one-market-s-slice-4",
            "sha": "0377c338f724e8469475bd80170689ada36f230d",
            "subject": "agent: federation 50-500X extensions (a-d), all four"
          },
          {
            "committed_at": 1786017963,
            "ref": "agent/dropbox-cross-app-hivemind-federation-one-market-s-slice-5",
            "sha": "360207b4b3e0549a24bcd880453c7577fb31f962",
            "subject": "agent: federated entity resolution \u2014 illuminati side of the identity spine"
          },
          {
            "committed_at": 1785970833,
            "ref": "agent/dropbox-cross-app-hivemind-federation-one-market-shaped-intelligence-50-500x-extensions-build-all",
            "sha": "395038582d3c3c846fb48ea47024180ea9e7f127",
            "subject": "agent: federation 50-500X extensions (a-d), all four"
          },
          {
            "committed_at": 1786022958,
            "ref": "agent/dropbox-foulkon-the-decision-instrument-full-implementation-group-1",
            "sha": "bfebb4bc9493f737eabd1ce1bb3eff41117dfa3e",
            "subject": "agent: dropbox-foulkon-the-decision-instrument-full-implementation-group-1"
          },
          {
            "committed_at": 1786025286,
            "ref": "agent/dropbox-foulkon-the-decision-instrument-full-implementation-group-3",
            "sha": "6fdf7204ebae5b625140d58e468f747686c22e1a",
            "subject": "agent: dropbox-foulkon-the-decision-instrument-full-implementation-group-3"
          },
          {
            "committed_at": 1786023933,
            "ref": "agent/dropbox-foulkon-the-decision-instrument-full-implementation-group-4",
            "sha": "1a07e1a9007e2a5fc8bfef2cd6b5c2b4ca83520e",
            "subject": "agent: dropbox-foulkon-the-decision-instrument-full-implementation-group-4"
          },
          {
            "committed_at": 1786023491,
            "ref": "agent/dropbox-operator-approved-full-improvements-document-build-in-full-2-contracts",
            "sha": "049321e9f3c2505b1b515e445df78b8fc23666e6",
            "subject": "agent: dropbox-operator-approved-full-improvements-document-build-in-full-2-contracts"
          },
          {
            "committed_at": 1786025698,
            "ref": "agent/dropbox-operator-approved-full-improvements-document-build-in-full-2-group-3",
            "sha": "d5cabfebee16ffacca59fcf8000336cd1e380fa6",
            "subject": "agent: dropbox-operator-approved-full-improvements-document-build-in-full-2-group-3"
          },
          {
            "committed_at": 1786025537,
            "ref": "agent/dropbox-operator-approved-full-improvements-document-build-in-full-2-group-4",
            "sha": "e80e6dc6c05b1151a0992dcdadabaaaf78eefeba",
            "subject": "agent: dropbox-operator-approved-full-improvements-document-build-in-full-2-group-4"
          },
          {
            "committed_at": 1786026534,
            "ref": "agent/dropbox-operator-approved-full-improvements-document-build-in-full-2-group-5",
            "sha": "cb5471d23e187a736718761d3a4b5eb096a57cef",
            "subject": "agent: coverage map + versioned-everything (group-5, illuminati side)"
          },
          {
            "committed_at": 1786025987,
            "ref": "agent/dropbox-precedent-graph-compression-corpus-wide-zero-token-reasoning-group-1-cit",
            "sha": "37f338b184f69e1c4f673b89e4459e86d23afa3b",
            "subject": "agent: dropbox-precedent-graph-compression-corpus-wide-zero-token-reasoning-group-1-cit"
          },
          {
            "committed_at": 1786138410,
            "ref": "agent/dropbox-tomorrow-foulkon-hedge-bridge-transferspec-population-1-clic-group-1",
            "sha": "4f3122c824accf99b557b80f3efc4308abe72f28",
            "subject": "agent: dropbox-tomorrow-foulkon-hedge-bridge-transferspec-population-1-clic-group-1"
          },
          {
            "committed_at": 1786025808,
            "ref": "agent/dropbox-tomorrow-foulkon-hedge-bridge-transferspec-population-1-clic-group-4",
            "sha": "7155dce13c71121190e04dd8f8e5be990fa436b3",
            "subject": "agent: hedge 1-click submits an indication and opens consent, never a trade"
          },
          {
            "committed_at": 1786024460,
            "ref": "agent/dropbox-tomorrow-foulkon-hedge-bridge-transferspec-population-1-clic-group-5",
            "sha": "a644c61de004fcbe9ec15381408a1c284662415c",
            "subject": "agent: dropbox-tomorrow-foulkon-hedge-bridge-transferspec-population-1-clic-group-5"
          },
          {
            "committed_at": 1786026865,
            "ref": "agent/dropbox-vigil-foulkon-enforcement-bridge-enforcementspec-population-group-4",
            "sha": "1893305f67fb542e0bdb52125ae124bac9356048",
            "subject": "agent: dropbox-vigil-foulkon-enforcement-bridge-enforcementspec-population-group-4"
          },
          {
            "committed_at": 1785963949,
            "ref": "agent/recover-missing-branch-backlog-batch-illuminati-d3ba8c6-weekly-lint-fix-typechec",
            "sha": "8de7c7ba8891f83dcc5748c2e547152e9a475d7c",
            "subject": "recovery-intent-stub: recover-missing-branch-backlog-batch-illuminati-d3ba8c6-weekly-lint-fix-typechec"
          },
          {
            "committed_at": 1785182261,
            "ref": "chatgpt/post-hardening-selftest-07271457",
            "sha": "13f7b62bb4531015f9641dce1e1eaa856278ffbe",
            "subject": "chore: post-hardening bridge selftest"
          },
          {
            "committed_at": 1786521353,
            "ref": "fix/fail-closed-supabase-config-20260812",
            "sha": "ad653f7f91f9ab320002a59befb0d9f7ba5ca9d1",
            "subject": "fix(config): make Supabase clients fail closed instead of defaulting to a hardcoded project"
          },
          {
            "committed_at": 1786026865,
            "ref": "orchestrator/dev",
            "sha": "1893305f67fb542e0bdb52125ae124bac9356048",
            "subject": "agent: dropbox-vigil-foulkon-enforcement-bridge-enforcementspec-population-group-4"
          }
        ],
        "branches_total": 32,
        "count": 32,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/illuminati"
      }
    ]
