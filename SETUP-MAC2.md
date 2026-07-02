# Add a second machine (scale-out) — and how cloud fits later

## The short answer to "do we need cloud now?"
**No.** You do not need cloud capacity to double throughput. The runner coordinates entirely through
Supabase: every task claim ends with an **atomic optimistic update** (`state=QUEUED → RUNNING`, guarded
by `state=eq.QUEUED`). Two machines pulling the same queue therefore **cannot double-claim** a task —
whoever's PATCH lands first wins, the other simply picks the next task. So scale-out is literally
"run the same runner on another box pointed at the same Supabase project." No central coordinator, no
code changes.

Your second Mac (same specs) becomes **N=2** today. Cloud is the *same* switch flipped again later:
when you want N=3+, spin up a Linux box, clone the repo, drop in the same `.env`, make the app repos
reachable, and run `runner.py`. Build-once, flip-when-needed — nothing here is Mac-specific except the
paths, which are configurable.

## Fleet math
- Each machine runs **one** runner (enforced by a per-machine file lock).
- Each runner does up to `MAX_PARALLEL=4` concurrent tasks, **RAM/disk-gated** by `resource_governor`
  so it never crashes the box.
- Two Macs → **fleet ceiling ≈ 8 concurrent tasks**. `fleet.py` reports live machines + capacity.

## Steps on Mac #2
1. **Clone the orchestrator repo** to the same relative location (recommended):
   `~/Documents/beethoven/claude-orchestrator`.
2. **Copy `runner/.env` from Mac #1 verbatim** — same `SUPABASE_URL` + `SUPABASE_SERVICE_KEY` (that's
   what points it at the shared queue), same provider keys, same model defaults.
3. **Make the app repos reachable at the same paths.** `projects.repo_path` in the DB is absolute. Two
   clean options:
   - Clone each app repo to the identical path on Mac #2, **or**
   - Keep Mac #2 focused on a subset by pausing the projects whose repos aren't present (the runner
     skips paused projects; it also safely skips a task whose repo path doesn't exist).
4. **Install the Claude CLI and log in.** Subscription mode uses the logged-in Max session. Use *your
   own* authorized account(s). If you want both Macs coding Claude tasks heavily in parallel, add a
   second authorized login to `account_pool` so they don't contend on one subscription's rate limit —
   this is account *rotation across your own logins*, not sharing one seat to evade limits.
5. **Run it:** `cd runner && set -a; source .env; set +a && python3 runner.py`
   (or install the launchd plist so it survives reboots — same as Mac #1).

## Verify the fleet
```bash
cd runner && python3 fleet.py     # should list BOTH hosts as live, ceiling ~8
```
Or SQL: `select hostname, active_tasks, last_seen from runner_heartbeats
         where last_seen > now() - interval '180 seconds';`

## What each machine does automatically
- Pulls the highest **priority × ROI** work first (economic scheduler in `db.claim_task`).
- Throttles itself on RAM/disk (`resource_governor`) — independently per machine.
- Honors the **global kill switch** and the **real-$ circuit breaker** (shared via the DB / per-machine
  call budget), so adding a machine cannot blow the spend caps.

## When you actually want cloud
Add cloud when you need **N>2**, want 24/7 capacity independent of your Macs being awake, or want a
machine geographically closer to a provider. The migration is the same five steps on a Linux box. Until
then, N=2 on your two Macs is free and sufficient.
