# Horizontal scale: N cloud runners

The runner is already stateless against Supabase (`claim_task` does an atomic optimistic
PATCH, so two runners never double-claim — see `db.py::claim_task`), and
`account_partition.py` already exists to prevent two machines from burning the same account
simultaneously. Containerizing it is mechanically simple (`deploy/Dockerfile.runner`,
`deploy/docker-compose.runners.yml`). What is **not** simple, and is a decision only you can
make, is subscription auth.

## The real constraint: auth, not code

Claude Code's Max subscription auth is a logged-in session tied to an account, not an API
key. `subscription_guard.py` exists specifically to keep this fleet on that subscription
auth instead of direct API billing (the ~$500 June invoice was direct API spend). That means
horizontal scale has exactly two honest paths:

1. **N subscriptions.** Each cloud runner container needs its own `claude login` session
   (persisted to the `/data` volume declared in the Dockerfile). This is the path that
   preserves the current $0-marginal-cost-per-token model, but it means paying for N Max
   subscriptions, not N containers.
2. **Deliberate paid API fallback for the overflow lanes.** Set `ORCH_USE_SUBSCRIPTION=false`,
   `ORCH_ALLOW_API_BILLING=true`, `ORCH_USE_PURCHASED_CREDITS=true` on specific overflow
   containers only, with `ORCH_API_DAILY_USD_CAP` set to a number you're deliberately willing
   to spend. `billing_guard.py` and `pause_arbiter.py` still protect you here — a real-spend
   trip pauses that scope and stays paused for a human, it does not auto-clear.

There is no third option where containers multiply capacity for free. Anyone proposing "just
containerize it" without addressing this is describing steps 3-10 of a plan that doesn't have
a step 1-2.

## What you get once auth is sorted

- `RUNNER_HOSTNAME` (mapped to `account_partition.py`'s `machine` column) gives each
  container primary/secondary account affinity, same as the two-Mac setup today.
- `ORCH_RUNNER_FLEET_TARGET` / logical runners (`db.py::heartbeat`) already let one process
  report multiple "lanes" to the dashboard — useful for right-sizing `MAX_PARALLEL` per
  container against its actual CPU/RAM.
- `pause_arbiter.py`, `fleet_stuck_alarm.py`, and `scoreboard.py` are global (Supabase-backed
  `controls` rows), so they work identically whether you have 1 Mac or 12 containers — no
  per-runner changes needed.
- Repos/worktrees are NOT shared across containers (each `git worktree` assumes exclusive
  filesystem access) — give each runner its own checkout, not a shared volume, or you will
  get exactly the kind of file-collision bugs `setup-worktrees.sh` was built to prevent.

## Suggested rollout

1. Get ONE cloud container running against a throwaway/staging project with a real
   subscription login, confirm it claims and merges a task end to end.
2. Watch `scoreboard.py`'s `usd_per_merge` and `merge_rate` for that container for a day —
   cloud CPU/network characteristics differ from a Mac, and toolchain_gate/dependency_prewarm
   assumptions (npm/tsc in PATH, node_modules warming) need to hold in the container image
   too.
3. Only then decide how many subscriptions (path 1) vs. how much deliberate paid-API budget
   (path 2) you actually want, and scale `docker compose ... --scale runner=N` accordingly.
