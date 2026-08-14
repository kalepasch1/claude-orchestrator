# Generator audit: why tasks are created that cannot produce code

Companion to `runner/recovery_admission.py`. Item 4 of
`no-task-without-recoverable-input-cowork-20260806` asks for a per-generator mechanism
report **and explicitly asks not to change the other generators in this task**. Nothing
here is implemented; this is the evidence for a follow-up decision.

Measured 2026-08-06 against the live `tasks` table. "Produced" = reached
`MERGED` / `DONE` / `DEPLOYED_AND_VERIFIED`.

| generator | total | phantom | produced | % produced |
|---|---:|---:|---:|---:|
| other | 8,978 | 3,482 | 1,833 | 20.4% |
| `recover-*` | 3,865 | 2,570 | 871 | 22.5% |
| `improve-*` | 2,576 | 1,849 | 234 | **9.1%** |
| `cont-*` | 1,903 | 953 | 296 | 15.6% |
| `canary-*` | 1,782 | 715 | 505 | 28.3% |
| `dropbox-*` (operator) | 1,187 | **0** | 280 | 23.6% |
| `rework-*` | 873 | 655 | 155 | 17.8% |

Two things stand out before any per-generator detail.

**`recover-*` is the largest phantom producer in absolute terms (2,570), but not the
worst by rate.** At 22.5% produced it is close to the fleet average and *better* than
`improve-*`, `cont-*` and `rework-*`. Its cost is volume, not hopelessness — consistent
with the diagnosis that most recoveries are structurally impossible while a real minority
are legitimate. That is exactly the split the admission gate is built to make, and it is
the reason the gate refuses on *absence of input* rather than on the `recover-` prefix.

**`dropbox-*` has zero phantoms across 1,187 tasks.** Operator-origin work never claimed
a merge it did not make. Every phantom in this system is machine-generated. This is the
strongest available justification for the operator-origin exemption in the gate.

## Per-generator mechanism

### `recover-*` — 3,865 tasks, 2,570 phantom
Addressed by this change. The failure is asking an agent to recreate a patch that no
longer exists in any form. Recursion is real but **does not nest the way the slug shape
suggests**:

| shape | rows |
|---|---:|
| `recover-missing-branch-recover-missing-branch-…` (literal doubled prefix) | **0** |
| `recover-missing-branch-…rework-…` | 507 |
| `rework-…recover-missing-branch-…` | 102 |
| `recover-missing-branch-…recover…` (any) | 105 |

Recursion travels **through the repair path**, not by direct self-application. A
depth counter that only strips leading prefixes scores all 507 of the dominant shape as
depth 1 and the cap would never fire. `recovery_depth()` therefore counts every
occurrence of the prefix anywhere in the slug. This was found by measurement after the
first implementation used leading-prefix counting; the original approach would have
shipped an inert cap.

### `improve-*` — 2,576 tasks, 234 produced (9.1%) — **worst rate in the fleet**
Not gated here, and it is the strongest candidate for the next intervention: it is second
in volume and last in yield. Mechanism is different in kind from recovery — an `improve-*`
task *has* a target repo and *can* commit, but the prompt states no acceptance criterion,
so there is nothing that distinguishes done from not-done. Recommended follow-up: require
a named file/symbol target or a stated observable before admission. **Not** a recoverable-
input problem, so the gate in this change would be the wrong tool.

### `cont-*` — 1,903 tasks, 15.6%
Continuation tasks inherit an ancestor's prompt without inheriting its progress, so
several agents re-derive the same starting point. Suspected duplicate-work rather than
impossible-work. Needs a lineage check before admission; not measured further here.

### `canary-*` — 1,782 tasks, 28.3% — **exempt, and the metric is wrong for them**
Canaries are probes. A canary that runs, proves the lane is alive and commits nothing has
**succeeded**. Counting them as failed producers overstates the phantom problem by ~715
tasks and, worse, would create pressure to make probes emit code — which would destroy
their purpose. Recommendation as the spec anticipates: **exempt canaries from the
code-production metric** rather than "fix" them. `recovery_admission.is_canary()` exists
for this classification; the gate never touches them.

### `rework-*` — 873 tasks, 17.8%
Rework is the repair path, and per the table above it is also the vehicle by which
recovery recursion nests (507 + 102 rows). Capping recovery depth reduces rework input as
a side effect. Worth re-measuring after this change rather than acting now.

## What this change does and does not do

Does: refuse `recover-*` admission when no branch, no artifact commit and no stored diff
exists; cap recursion depth (`ORCH_RECOVERY_MAX_DEPTH`, default 2); record every refusal
in `admission_rejections` naming the original slug.

Does not: touch the existing 9,918 terminal tasks (explicitly out of scope — a separate
operator decision under `bulk_state_change_audit`), disable recovery, or change
`improve-*` / `cont-*` / `canary-*`.

**Fail-soft, and this was nearly wrong.** The first implementation swallowed DB errors in
the input probes and returned "no rows", which is indistinguishable from "no recoverable
input" — a transient database outage would have refused *every* genuine recovery in the
fleet at once. That is precisely the over-eager gate the spec warns is worse than the gap.
Probe failure now raises `ProbeUnavailable`, `check()` catches it and allows the task with
`alarm=True`. Pinned by `test_gate_fails_open_with_an_alarm`, which caught the bug.
