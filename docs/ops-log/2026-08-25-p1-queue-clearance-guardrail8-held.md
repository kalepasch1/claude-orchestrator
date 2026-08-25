# P1 queue clearance — Guardrail 8 held (2026-08-25 11:07 UTC)

Slug: `log-p1-queue-clearance-guardrail8-held-20260825-qh7v`
Playbook: orch-operator, P1 queue clearance. Steps **not** executed this run:
dead-weight triage, throughput/concurrency raise, prioritize-by-value.

Guardrail 8 — *no improvement across two consecutive runs → stop and escalate* —
remains tripped. This entry records the measurement, corrects two numbers the
queued prompt carried, and names a candidate cause the hourly log series has not
yet named.

## Measured this run (re-derived, not transcribed)

| metric | value |
|---|---|
| `tasks` QUEUED | 327 |
| `tasks` RUNNING | 3 |
| p90 queued wait (`percentile_cont(0.9)` over age in hours) | 1135.0 h (~47.3 d) |
| MERGED in last 2 h | 0 |
| DEPLOYED_AND_VERIFIED in last 2 h | 0 |

Same signature as prior runs: QUEUED flat at 327 while the p90 tail keeps aging
(1133.9 → 1134.9 → 1135.0 h across the last three hourly checks). Throughput is
not slow, it is zero — nothing has merged or deployed in two hours.

## Corrections to the queued prompt

The prompt for this log task asserted two ages that do not match the database.
Recording them so the hourly series stops propagating the error:

- `escalate-p1-queue-clearance-no-improvement-20260814-hlt9` — prompt said
  **425.9 h / 17.7 d**; actual age is **258.1 h / 10.8 d**. The 425.9 h figure
  belongs to `tp91`, not `hlt9`; the two appear to have been transposed.
- `human-decision-unpause-runner-hosts-20260807-tp91` — prompt said 423.4 h;
  actual **423.5 h**. Consistent.

## Open items blocking the guardrail (all `operator_approved_at IS NULL`)

| slug | state | priority | age |
|---|---|---|---|
| `escalate-p1-queue-clearance-no-improvement-20260810-nk73` | DECOMPOSED | 5 | 349.1 h |
| `escalate-p1-queue-clearance-no-improvement-20260814-hlt9` | DECOMPOSED | 48 | 258.1 h |
| `human-decision-unpause-runner-hosts-20260807-tp91` | DECOMPOSED | 5 | 423.5 h |

`human-decision-fund-executor-outage-20260824-qz4m` is `state=DONE` with
`operator_approved_at`/`operator_approved_by` still NULL — a human-decision row
that closed without a recorded decision. Carried forward as an anomaly, not
treated as a resolution; it does not change the blocking condition, so `hlt9`
remains the controlling open escalation.

## Candidate cause not previously named: the verification pause never lifted

`controls` still holds **nine `scope=project` rows paused 2026-08-24 03:53–03:57
UTC** with the reason:

> "controlled fleet verification 2026-08-24: paused so the ONLY project a runner
> can claim is smoke-test, which is a local repo with no remote. **REVERSIBLE —
> this is lifted the moment the verification finishes.**"

Those pauses are **31.2 hours old**. The stated lifecycle was minutes, tied to a
verification run that is long over. While they stand, essentially every real
project is unclaimable and the only claimable target is a local repo with no
remote — which is an exact mechanical explanation for QUEUED flat at 327,
RUNNING in the low single digits, and merged/deployed pinned at 0.

This is distinct from, and likely upstream of, the provider-credit outage
recorded on `scope=global` (paused 30.8 h, same window). Un-pausing global
without also clearing these nine project rows would leave throughput at zero.

Also still standing, unrelated to the verification window:

- `scope=host` — three hosts paused since 2026-08-07 (439.8 h) under the
  >7-day dead-host threshold; resume requires human verification.
- `scope=project` — one row paused by Bear 2026-08-15 (230.1 h) pending review
  of unreviewed agent branches; one paused with reason `"test"` (134.0 h).

## Acceptance (unchanged)

A human reviews `hlt9` and `tp91`, sets `operator_approved_at` /
`operator_approved_by` or explicitly closes/supersedes each with a recorded
decision, and either authorizes resuming the playbook or formally retires it.
Done = neither row satisfies
`operator_approved_at IS NULL AND state IN ('QUEUED','DECOMPOSED','BLOCKED')`.

Suggested addition, given the finding above: confirm whether the 2026-08-24
verification is finished and, if so, clear the nine `scope=project` pauses. The
`"test"` pause should probably go with them.

## Guardrails observed

No state changes to `tasks` / `approvals` / `releases` / `runner_alerts`. No
DELETEs. No host un-pause (human-required). No funding or spend action. No
duplicate escalate/human-decision task created — `hlt9` and `tp91` were
dedup-checked and remain open. No push notification sent; the ~11:01 UTC run
already alerted on this identical unchanged condition.
