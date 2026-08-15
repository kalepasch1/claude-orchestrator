# Recovery ledger — beethoven — local-only branch tips

- audit fingerprint: `6ab23a17164907b6f2eac04573697a77138c8fa5a52aab0aeb992c7947f9268a`
- base: `origin/master`
- evidence items classified: **33**
- UNKNOWN remaining: **0**

Every rescue ref was treated as read-only. No ref, stash or worktree
was deleted, reset, cleaned, popped or moved by this reconciliation.

## Classification summary

| classification | count |
| --- | ---: |
| RECOVERABLE_VALUE | 4 |
| ACTIVE_IN_ANOTHER_TASK | 14 |
| SUPERSEDED_BY_NEWER | 7 |
| ALREADY_PRESENT | 8 |

## Items needing follow-up

| ref | sha | class | files | disposition |
| --- | --- | --- | ---: | --- |
| `heads/agent/dropbox-hisanta-mastery-engine-grandma-rail-family-slice-2-clean-129448` | `358297faa1` | RECOVERABLE_VALUE | 11 | range diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `heads/agent/improve-missing-branch-auto-creator-slice-3-locate-decomposition-event-handler-a-clean-152441` | `dc65c5428c` | RECOVERABLE_VALUE | 4 | range diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `heads/agent/improve-value-aware-test-routing-early-exit-r-slice-3-fix-broken-tests-clean-151469` | `a9e98fc3c7` | RECOVERABLE_VALUE | 3 | range diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |
| `heads/backlog-batch-illuminati-1d1b027` | `0abf5b6d4c` | RECOVERABLE_VALUE | 5 | range diff applies cleanly to base; recover via isolated worktree + agent branch through the merge train |

## Disposition rules applied

- `ALREADY_PRESENT` — reachable from base, patch-identical to base, or an
  empty sweep commit. No action.
- `SUPERSEDED_BY_NEWER` — every touched path was rewritten in base after the
  ref was cut. Newest implementation wins; no action.
- `ACTIVE_IN_ANOTHER_TASK` — the commit is contained in a live `agent/*`
  branch. Left to that task; not duplicated here.
- `RECOVERABLE_VALUE` — diff still applies. Recover through an isolated
  worktree and the normal agent-branch + merge-train path.
- `CONFLICTED_NEEDS_FOCUSED_TASK` — diff no longer applies. A focused
  follow-up is queued instead of forcing an overwrite.
