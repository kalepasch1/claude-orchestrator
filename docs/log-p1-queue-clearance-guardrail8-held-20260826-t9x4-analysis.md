# P1-queue-clearance — Guardrail 8 held (run 2026-08-26 12:00 UTC)

**Task:** `log-p1-queue-clearance-guardrail8-held-20260826-t9x4`
**Kind:** `log` (zero-row-touching — no state changes to `tasks`, `approvals`, `releases`, `runner_alerts`)
**Playbook:** orch-operator P1-queue-clearance
**db now() at re-derivation:** 2026-08-26 12:00:31 UTC

## 1. Status: held

Guardrail 8 (no improvement across two consecutive runs → stop, escalate, do not
continue) remains tripped. Held this run: (a) dead-weight triage, (b)
throughput/concurrency raise, (c) prioritize-by-value. No bulk state change was
executed, so no `bulk_state_change_audit` row is required.

## 2. Independently re-derived metrics

All figures below were re-derived by this session's own SQL against
`eatfwdzfurujcuwlhdgj`, not carried forward from the originating prompt.

| Metric | 07:59 UTC (claimed) | 12:00 UTC (measured) | Direction |
|---|---|---|---|
| `tasks` QUEUED | 266 | **264** | noise |
| `tasks` RUNNING | 0 | **2** (both this executor's own claims) | no real change |
| MERGED/DEPLOYED_AND_VERIFIED in last 4h | 0 | **0** | flat, dead |
| MERGED/DEPLOYED_AND_VERIFIED in last 24h | — | **1** | effectively dead |
| p90 QUEUED wait | 1156.0h (48.2d) | **1160.1h (48.3d)** | still climbing |

Throughput remains at zero. The p90 wait continues to rise monotonically, which
is the expected signature of an arrival-only queue: work enters, nothing leaves.

## 3. Open decision tasks — all three reconfirmed unactioned

Verified by direct slug lookup this run. None has `operator_approved_at` /
`operator_approved_by` set; none has been closed or superseded.

| Slug | State | Kind | Age |
|---|---|---|---|
| `escalate-p1-queue-clearance-no-improvement-20260810-nk73` | DECOMPOSED | improve | 15.6d |
| `escalate-p1-queue-clearance-no-improvement-20260814-hlt9` | DECOMPOSED | improve | 11.8d |
| `human-decision-global-pause-past-eta-20260826-fq83` | DECOMPOSED | human-decision | 0.3d |

No new escalate/human-decision task was filed this run — dedup confirmed against
all three above before deciding.

## 4. NEW THIS RUN — the blocker is a pause *stack*, not a single pause

Prior entries in this series name the `global` pause as "the root blocker,"
singular. Full enumeration of `controls` this run shows that framing is
incomplete, and the difference is operationally material.

| Scope | Paused | Rows | Oldest row stale |
|---|---|---|---|
| `global` | true | 1 | 55.7h |
| `host` | true | 3 | 464.7h (19.4d) |
| `project` | true | **16 of 17** | 447.8h |
| `orch_operator` | false | 1 | 1.0h |
| `config` | false | 1 | — |

Of the 16 paused `project` rows:

- **9** carry the reason *"controlled fleet verification 2026-08-24 … the ONLY
  project a runner can claim is smoke-test … REVERSIBLE — this is lifted the
  moment the verification finishes."* The verification is long over. The pause
  was never lifted. These rows are 56.1h stale.
- **12** describe themselves as REVERSIBLE or as a "manual restart," including
  two from 2026-08-09 (~420h stale) and one whose entire stated reason is the
  string `"test"` (158.9h / 6.6d stale).
- 1 is Bear's own deliberate 2026-08-15 hold ("fleet merging unreviewed agent
  branches into local main (115 ahead of origin); prod stale 3d") — that one is
  a real review gate and should stay until reviewed.

**Consequence:** resolving the funding/credit issue named in the `global` pause
reason will *not* restart the fleet. Even with `global.paused=false` and
providers funded, 16 project rows and 3 host rows still block claiming, and 9 of
those project rows exist only as leftovers from a finished 2026-08-24
verification that promised to lift itself and did not.

This is the specific failure mode that keeps re-tripping Guardrail 8: each run
correctly reports "throughput is zero, awaiting a funding decision," a human
could act on funding, throughput would stay at zero anyway, and the next run
would report no improvement — indefinitely. The escalations are accurate but
under-scoped.

## 5. Acceptance criteria (revised, superset of prior runs)

1. A human reviews `nk73`, `hlt9`, and `fq83`, and for each either sets
   `operator_approved_at`/`operator_approved_by` or explicitly closes/supersedes
   it with a recorded decision.
2. A human resolves the provider-credit / Claude-limit question behind the
   `global` pause.
3. **New:** the 9 `controls` rows from the finished 2026-08-24 "controlled fleet
   verification" are un-paused, since their own stated reason says they should
   already have been. Same for the 2026-08-09 "manual restart (reversible)" rows
   and the row whose reason is `"test"`.
4. The 3 `host` rows paused 2026-08-07 on the >7-day dead-host threshold are
   either verified live on current code and resumed, or formally retired.
5. Only after 1–4 is the playbook authorized to resume; otherwise it should be
   formally retired or re-scheduled rather than left to re-trip Guardrail 8.

Steps 3 and 4 are human-required. This automation does not un-pause `global`,
`host`, or `project` scopes, and did not attempt to this run.

## 6. Guardrails observed

- No force-push; branch is `agent/log-p1-queue-clearance-guardrail8-held-20260826-t9x4`.
- No writes to `tasks`, `approvals`, `releases`, or `runner_alerts`; read-only SQL only.
- No DELETEs, no TRUNCATE, no bulk state change, no `priority=5` bulk update.
- No `global`/`host`/`project` un-pause attempted — human-required by policy.
- No funding or spend action taken.
- No duplicate escalate/human-decision task filed; dedup confirmed against nk73,
  hlt9, fq83.
- No direct Vercel deploy; release-train only.
