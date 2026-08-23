# Lease-night stash recovery — section 3 (group 4)

Operator directive 2026-07-30. Source of truth for the recovered work:
`hotfix/stash-rescue-lease-night-5f879035` (= `hotfix/stash-rescue-1785390774-5f879035`,
same commit `5f879035`, authored 2026-07-29 13:44).

Section 3 covered three files. The directive said to re-apply "with judgment, not a
blind patch," and to verify against current state first because these files have moved
substantially. They had. Verdict per file, measured against `origin/master` @ `ddb87004`:

| File | Rescue delta | Verdict |
|---|---|---|
| `runner/merge_train.py` | restore the per-project worker (`process_project`) that the half-landed refactor deleted | **already present, superseded** — master carries the fix plus `regressfail`/`buildfail` outcomes the rescue lacked |
| `runner/deployment_bindings.json` | add the `apparently-law` binding; set beethoven's `vercel_project` to `claude-orchestrator` | **already present / superseded** — `apparently-law` is on master; the `vercel_project` value was changed to `web` later, by `67f15561` (2026-08-06), which is newer than the rescue |
| `scripts/fleet_config_baseline.json` | `ORCH_PUSH_ON_RELEASE`: `true` → `false` | **not applied — deliberate** (see below) |

## Why `ORCH_PUSH_ON_RELEASE` was not flipped

It is the only genuinely unrecovered delta in section 3, and it is the one that should
not be recovered blind. Flipping it to `false` halts production pushes fleet-wide. The
rescue snapshot was taken mid-incident on the lease-RPC night — a `false` there reads as
an incident hold, not a settled policy, and nothing in the directive or the surrounding
commits states the intent. Master has deliberately carried `true` since. Re-applying a
release kill-switch from a seven-day-old incident stash, on inference alone, is exactly
the blind patch the directive warned against. Left as-is; flip it explicitly if the hold
was in fact intended.

## What was actually missing

Not code — a guard. The `merge_train.py` fix was written twice: master's own comment
records that the first attempt "was wiped by the fleet's own stash/reset before it could
be committed." The recovery task then ran 70+ times with nothing asserting the shape had
been restored, because the worker is a closure inside `_train_run_unleased()` — it cannot
be imported or called directly, and a `NameError` in it is swallowed by the per-project
`try/except` in `process_project_isolated()`. That is why a three-day release freeze
presented as silence.

`runner/tests/test_merge_train_structure.py` closes that hole. It parses `merge_train.py`
and asserts the intended shape via AST rather than text, so it survives renames,
reformatting and comment edits, and fails only on the real defect:

- `train_run()` still delegates to `_train_run_unleased()` (lease wrapper intact)
- `_train_run_unleased()` defines `process_project`
- `process_project_isolated()` actually calls it
- `process_project` assigns `result` and returns it
- `process_project` takes exactly one `(pid, group)` item, matching the executor's `map`

Verified by reintroducing the original defect: the guard fails, and passes again once
reverted. The 12 failures / 3 errors in the pre-existing `tests/test_merge_train.py` are
present on clean `origin/master` and are unrelated to this change.
