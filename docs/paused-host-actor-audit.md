# Which fleet actors a host pause should cover

Item 5 of `host-pause-must-cover-trains-not-just-claims-cowork-20260806`:
*"Audit for other actors a pause should cover: sweepers, canary runners, anything
that writes fleet-visible state. List what you find and whether each should be gated."*

Method: for every module that writes state other hosts read, check whether it
consults `kill_switch.is_paused()` (or the new `paused_host_guard`) before starting.

## Gated in this change

| Actor | Writes | Why it must be gated |
|---|---|---|
| `release_train.run` / `run_for` | `releases`, production branches | The reported incident. A paused, 40-commits-stale host wrote `deploy_status='failed'`, flipping projects RED and tripping `ORCH_RELEASE_BACKPRESSURE` fleet-wide. |
| `release_train._insert_failed_release` | `releases` (gate verdicts) | This is the specific row that flips a project RED. Guarded separately because gates run outside `run()` too. |
| `merge_train.train_run` | agent branches, `orchestrator/dev`, task states | Pushes to shared branches from a stale checkout; the same class of damage as the 54 PUSH-VERIFY-FAILED sha-mismatches that motivated `integration_owner`. |

## Found unguarded — recommended, NOT done here

Listed rather than changed: this task is MATERIAL and lands for human review, and
silently widening a pause to eleven more subsystems in the same commit would make
that review much harder to do honestly. Each is a small follow-up.

| Actor | Writes | Gate? | Reasoning |
|---|---|---|---|
| `deploy_verify` | `releases.deploy_status`, rollbacks | **No** | Verifying and rolling back is *completing* work already in flight. Gating it would strand a half-deployed release — the exact failure the claim guard's design forbids. |
| `promotion` | `fleet_config`, promotion state | **Yes** | Promotes config fleet-wide from a host whose own config may be 40 commits stale. |
| `auto_tune_applicator` | `fleet_config` | **Yes** | Same: a stale host tuning the whole fleet's knobs. |
| `post_merge_smoke` | `fleet_config` markers, smoke verdicts | **Yes** | A red smoke verdict from a broken toolchain is indistinguishable from a real one. |
| `canary.py` | deploy promote/rollback verdicts | **Yes** | A rollback triggered by a paused host's metrics read is a production action. |
| `branch_repair_bot` | agent branches | **Yes** | Pushes branches; stale checkout means stale reconstructions. |
| `blocked_triage` | task states, `runner_alerts` | **Borderline** | Reclassification is cheap and reversible, but a stale host's idea of "blocked" is stale too. Low priority. |
| `stuck_reaper` | task states (quarantine) | **Borderline** | Quarantining burns attempts. A paused host reaping other hosts' work is wrong; reaping is also how the fleet self-heals. Needs thought, not a reflex gate. |
| `resource_medic` | `fleet_config` | **No** | Acts on THIS machine's local resources. A paused host still needs to manage its own disk. |

## The rule to apply to each

Block **starting** a new unit of fleet-visible work; never block **finishing** one.
That is why `deploy_verify` and `resource_medic` are "No" — they complete or are
host-local — and why the two trains are "Yes".

## Not fixed, and deliberately

`releases` rows already written by the paused host are left in place. They are
accurate records of what happened, and the RED state they caused was correct
given the input. The task said so explicitly, and it is right.
