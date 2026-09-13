# Database Steering: how much orchestrator is enough

Date: 2026-09-13 · Status: analysis, partially implemented · Trigger: operator review —
"consider eliminating the orchestrator app/orchestrator involvement and just working
directly on the projects code, the orchestrator only causes issues and errors thus far."

## What the review found

The concern has substance. The orchestrator's own code comments document months of
queue stalls, scan-window starvation, and silent invisibility (`merge_train._pick_cards`,
the TRUNCATED SCAN warnings, the drift-forensics hook). A pipeline whose failure mode is
"your work existed and nobody looked at it" is a real tax. The first live week of
database steering also showed the strength of the alternative: every outward artifact
landed better through direct channels than through orchestrator queues —

| Outcome | Orchestrated path | Direct path that worked |
|---|---|---|
| Getting `agent/db-steering` integrated | merge-train card: queued, correct, but invisible until the train's next pass | `git push` from the sandbox via the fleet's GitHub App — immediate |
| Remediation of anon-grant findings | swarm task rows, priority 1000, needing a swarm worker to pick up | draft PR kalepasch1/apparently-law#59 opened directly, SQL generated deterministically |
| Deploy gating | would require the orchestrator to sit in the deploy path (fragile) | commit status / marked commit comment posted on the repo and consumed by Vercel/GitHub rules natively |

The direct paths are also *debuggable*: GitHub and Vercel return real errors; a queue
returns silence.

## What the orchestrator still pays for

Three things only it provides today:

1. **The evidence store.** `db_findings`, posture snapshots, and the memo ledger are
   cross-project and longitudinal. Fleet medians (`db_baselines`) only exist because one
   place sees every database. A per-repo runner would fragment this.
2. **The coder-brief injection.** Prompt assembly is where steering reaches agents that
   build through the fleet. Repo-local sessions (Claude Code opened directly in a project)
   don't see it — see the recommendation below.
3. **Costless memo drafting cadence** with budget accounting against the local model.

None of these requires the orchestrator to *own the outward act* — only to own the
observation and the summary.

## Decision (conditional, reversible)

Keep the read-only observation and the ledger centralized; move every outward act
in-repo, where the change lives and the failure modes are visible:

- **Remediation** → draft PRs on the project repo (`db_remediate`), fingerprints joinable
  to `db_findings`, never auto-merged.
- **Deploy gating** → `db-steering/posture` commit statuses/comments on the project repo
  (`db_deploy_gate`); the *block* is configured natively (required check / Ignored Build
  Step), so the gate survives even if the orchestrator is down — when the signal stops
  posting, nothing gates, by design.
- **Coder briefs for direct sessions** → (proposed, not built) the loop commits
  `.claude/db-steering-brief.md` to the project repo when the brief's findings hash
  changes, so a directly-opened session steers itself without fleet prompt assembly.

The orchestrator keeps: probes, reconciliation, baselines, memos, and the queue of
*judgment* work (RLS policy design, query rewrites) for the swarm — the things that are
genuinely cheaper centralized.

## Not done in this pass, and why

- Deleting the swarm-task filing (`ORCH_DB_STEERING_REMEDIATION=false` stops it) is left
  as an operator switch, not a conclusion: only one remediation PR exists so far, and the
  PR path should prove out for a week before the queue is demoted.
- Repo-required-check wiring per project is a repo settings change, done by hand once per
  repo (flip `db-steering/posture` to a required status check after the App gains
  `statuses:write`).
