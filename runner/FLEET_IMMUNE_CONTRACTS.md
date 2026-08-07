# Fleet Immune System — shared contracts

**Status:** contracts only (v1.0.0). Operator directive 2026-08-02, highest priority.
**Module:** `runner/fleet_immune_contracts.py` · **Tests:** `tests/test_fleet_immune_contracts.py`

This task delivers *only* the shared vocabulary. The sibling work items implement the
actuators against it. Nothing here kills a process, writes a row, or schedules a daemon.

## Why contracts first

The 2026-08-02 incident was not one bug, it was seven independent blind spots that each
looked like something else. Every one of them was, at bottom, a **missing shared definition**:
nobody could say what "zombie", "leaked", "starved", or "held" meant, so each subsystem
guessed differently and none of them agreed with the operator's view. Fixing the actuators
without fixing the vocabulary reproduces the same drift a month later.

## Diagnosis → contract map

| # | Incident finding | Contract | Classifier |
|---|---|---|---|
| 1 | 64/66 coder lanes were zombies >1h old, pinning RAM + slots | `LaneSnapshot`, `LANE_ZOMBIE_AFTER_S` | `classify_lane` |
| 2 | `legal_docket.py` leaked 14 copies (8–10h old, 30-min interval) | `DaemonSnapshot` | `detect_daemon_leak` |
| 3 | mem-gate held claims — `claimable=803`, claiming ≈ 0 | `CapacitySignal` | `classify_capacity` |
| 4 | Mac 2's runner down from ~10:28 with **no alert** | `HostLiveness` | `classify_host` |
| 5 | sentinel train-stale false alarm: pressure in DB, sentinel watched a file | `AUTHORITATIVE_SOURCE` | — |
| 6 | release batch floor of 10 silently held small merges from prod | `ReleaseGate` | `evaluate_release_gate` |
| 7 | weak coder routes → `0/12 merged` on legal-class tasks | `RouteQuality` | `classify_route` |

## The three invariants siblings must honour

1. **Unknown is never healthy.** `classify_host` returns `down` when the heartbeat age is
   unknown. Mac 2 was dark for hours because "no data" and "fine" were the same value.
2. **Nothing is held or reaped without a reason.** Every `Verdict` that carries an `action`
   also carries a human-readable `reason`. Diagnosis (6) was a missing-reason bug: the batch
   floor was working as coded, and no log anywhere said so.
3. **The DB is the fleet's source of truth.** `AUTHORITATIVE_SOURCE == "db"`. File mirrors are
   advisory (offline mode, humans tailing logs). A consumer that reads only the file goes
   blind the moment the writer moves to the DB — diagnosis (5), for days.

## Shapes

* `Verdict(state, reason, action, subject, detail)` — the uniform classifier result.
  `verdict.actionable` is simply `bool(action)`; `to_dict()` is JSON-safe.
* States: `healthy`, `suspect`, `zombie`, `leaked`, `stuck`, `down`, `degraded`, `starved`,
  `held`, `release_ok`, `demote`.
* `sweep(lanes=, daemons=, hosts=, capacity=, gates=, routes=)` runs every classifier and
  returns only the actionable verdicts. **Actuators call `sweep`; they never re-derive a
  threshold.** A threshold that exists in two places has already diverged.

## Thresholds (env-overridable, defaults encode the incident)

| Env var | Default | Meaning |
|---|---|---|
| `ORCH_LANE_ZOMBIE_AFTER_S` | `3600` | lane age at which it is presumed dead |
| `ORCH_LANE_SUSPECT_AFTER_S` | `2400` | watch-only warning band |
| `ORCH_LANE_COUNT_WARN` | `25` | live lane count that suggests a leak resurfacing |
| `ORCH_DAEMON_LEAK_MAX_CONCURRENT` | `1` | copies of an interval daemon allowed at once |
| `ORCH_DAEMON_STUCK_INTERVAL_FACTOR` | `1.5` | multiple of its own interval before "stuck" |
| `ORCH_HOST_DOWN_AFTER_S` | `900` | heartbeat age that means down (alert the operator) |
| `ORCH_HOST_DEGRADED_AFTER_S` | `300` | heartbeat age that means lagging |
| `RELEASE_MIN_BATCH` | `1` | recovery-mode floor (was 10 — see diagnosis 6) |
| `ORCH_RELEASE_MAX_HOLD_S` | `3600` | age override: a waiting batch ships regardless of floor |
| `ORCH_ROUTE_MIN_SAMPLES` | `6` | evidence needed before demoting a route |
| `ORCH_ROUTE_MIN_MERGE_RATE` | `0.15` | merge rate below which a route is demoted |

## Migration stub

`FLEET_IMMUNE_EVENT_DDL` creates the append-only `fleet_immune_event` journal
(`host, subject, state, action, reason, detail jsonb, contract_ver`), idempotently. Siblings
apply it and write via `event_row(verdict, host)`. Append-only on purpose: an immune system
that can rewrite its own history cannot be audited after an incident.

## Rules for sibling implementations

- Import thresholds and states from this module. Do not redefine them.
- Emit one `event_row` per actionable verdict before acting, not after — an action that kills
  the process before it journals is an action that never happened.
- Keep actuators fail-soft. A classifier returning `healthy` on garbage input is intentional:
  the immune system must never be the thing that takes the fleet down.
- Changing a threshold's *meaning* means bumping `CONTRACT_VERSION`; the journal records the
  version each row was written under.
