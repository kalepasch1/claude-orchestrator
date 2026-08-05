# Lane sizing — measure it, don't guess it

`runner/.env` is gitignored, so the reasoning behind its resource numbers lives here.
Recalibrated 2026-08-04 after the fleet was found pinned to 19 lanes on a 48 GB Mac.

## The governor is correct; its inputs were stale

`resource_governor._vm_stat()` is accurate. It reads the page size dynamically (Apple
Silicon uses **16 KB** pages, not 4 KB — a hand-rolled parser assuming 4096 undercounts
available RAM by 4×) and treats reclaimable file cache as free, which Activity Monitor
agrees with.

The throttle is then clamped by:

    mem_budget = (free_ram - RAM_FLOOR_GB) / PER_TASK_GB

`PER_TASK_GB` was **0.5**, dating from when ollama ran inference **on-device**. Inference is
now entirely remote (`ORCH_DISABLE_LOCAL_MODELS=1`, zero ollama models resident), so a lane
is just an aider/claude CLI process talking to a cloud API.

**Measured, 20 live workers: mean 0.13 GB, 2.6 GB total.**

So the clamp reserved ~4× what a lane costs: `(15.0 - 6) / 0.5 = 18`. The Mac looked
memory-bound while ~15 GB sat available.

## Current values and why

| Key | Value | Rationale |
|---|---|---|
| `PER_TASK_GB` | 0.20 | Measured 0.13 + ~50% headroom |
| `RAM_FLOOR_GB` | 4 | 4 GB reserve on a 48 GB machine |
| `MAX_PARALLEL` / `MAX_PARALLEL_CEILING` | 40 | Clamp allows ~53; ceiling is the deliberate limit |

Effective lanes: **19 → 40**.

All four are listed in `ORCH_CONFIG_ENV_PINS`, so the local `.env` wins over any stale
`fleet_config` row — which is how the old values kept reasserting themselves.

## Re-measuring

Do this rather than adjusting `PER_TASK_GB` by feel:

    ps aux | grep -iE "aider|claude " | grep -v grep \
      | awk '{s+=$6; n++} END {printf "%d workers, mean %.2f GB\n", n, s/1048576/n}'

## What actually limits throughput now

RAM is no longer the binding constraint. In order:

1. **Account rate limits** — `account_pool` rotates across the accounts in the `accounts`
   table and honours `cooldown_until`. Accounts pinned to an offline machine via the
   `machine` column are idle capacity.
2. **The ceiling above** — raise it only alongside a fresh measurement.
3. **Cowork desktop scheduled tasks are NOT part of this budget.** They run inside the
   desktop app, capped at 3 concurrent globally, bound to the single signed-in account, and
   cannot use the account pool. Do not size the runner around them.
