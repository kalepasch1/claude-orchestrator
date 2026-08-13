# P1 — artifact_commit is not evidence (2026-08-12)

Supersedes `p0-executor-merged-state-is-not-evidence`, whose "33% phantom" headline was
retracted: both commits it named exist in beethoven, and the properly scoped fleet-wide
phantom rate is 5 of 1169 = 0.43%. The commits are real. **The attribution is not.**

## Measured

`python3 tools/audit_merged_evidence.py` — 300 of 1169 MERGED / DEPLOYED_AND_VERIFIED
tasks (25.7%) cite an `artifact_commit` that at least one other task also cites.
`47f26779` changes two files and is the claimed artifact of 32 distinct tasks.
`725b0b40` ("agent: qafix", 222 files) is claimed by 26; `54b69ee0` ("Merge all queued
improvements", 402 files) by 6.

`python3 tools/classify_shared_artifact_commits.py` — re-run 2026-08-12 over the same
300-task population:

| verdict | tasks |
|---|---|
| justified (shared commit touches the task's declared scope) | 205 |
| **unattributed** (shared commit, no file in the task's declared scope) | **95** |
| repo-less citation (R2 violation — bare sha, unverifiable by construction) | 300 / 300 |

Per-task audit rows: `reports/p1-shared-artifact-commit-classification-20260812.json`.
**No state was changed.** An unaudited bulk state change is itself a tracked defect here.

## What was built

`runner/artifact_evidence.py` — the evidence contract, pure logic, git injected as a
callable so it is unit-testable. 19 tests in `runner/test_artifact_evidence.py`.

- **R1 — an executor may not set MERGED.** `may_set_merged(actor_role, verdict)` refuses
  every executor-class role (`executor`, `coder`, `agent`, `runner`, `merge_train`,
  `batch_fusion`) outright, and refuses any verdict that did not resolve the sha in the
  target repo and confirm file overlap. Fails closed on an unknown role or a missing
  verdict.
- **R2 — a citation must name its repo.** `format_citation(repo, sha)` emits
  `"<repo>@<sha>"` and refuses to emit a repo-less one. `parse_citation` still reads the
  legacy bare sha but returns `repo_known=False`; a bare sha cannot be probed against the
  right repo, and probing it against the wrong one is exactly how both earlier audits
  scoped themselves wrong. Text encoding, so no migration is required to start writing
  verifiable citations.
- **R3 — a commit claimed by N>1 tasks is justified per task or not at all.**
  `classify_claim` returns `justified` only when the commit's changed-file set intersects
  that task's declared scope; otherwise `unattributed`, and the detail line says to record
  the sha as an integration commit and leave the task unverified on its own merits.
  Generic path tokens (`src`, `test`, `index`, `runner`, …) are dropped so they cannot
  launder a 402-file integration commit into a justified claim.
- **R4 — backfill classifies, it never bulk-updates.** `audit_row()` renders the record
  that must accompany any state change; `tools/classify_shared_artifact_commits.py` is
  read-only and has no `--apply`.

## Known, not re-derived

`account` cannot attribute outcomes. Commits written by hand in operator sessions
(`f73cad86`, `6dd4ff13`, `67b9e055` among them) are recorded against tasks whose `account`
still held the executor that had claimed them, so executor success statistics are inflated
by manual work.

## Not done here

The 95 unattributed tasks are classified, not re-stated — that is a verifier action, one
task at a time, each with its audit row. Wiring `may_set_merged` into the merge train's
write path is the next slice; it changes live merge behaviour and wants its own review.
The deploy agents and the executor lane remain unloaded by operator decision.
