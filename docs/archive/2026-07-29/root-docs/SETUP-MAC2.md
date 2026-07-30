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

## One-time DB setup from Mac #1
Apply the fleet-control schema once so both Macs can receive shared config and control commands:

```bash
cd ~/Documents/beethoven/claude-orchestrator
supabase db query --linked --file supabase/migrations/0033_fleet_control.sql
cd runner && python3 fleetctl.py bootstrap-defaults
```

If `supabase db push` is healthy on your machine you can use that instead, but the direct query command
works even when migration history is out of sync.

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
5. **Run the canonical setup:**
   ```bash
   cd ~/Documents/beethoven/claude-orchestrator
   bash scripts/setup-mac2.sh
   ```

The setup script sizes lanes to Mac 2's RAM, enables central auto-pull, installs the launchd
`ClaudeRunner.app` supervisor, configures local/value coder routes, and runs `fleet_doctor.py`.

## Full Disk Access
The runner needs Full Disk Access because app repos live under `Documents`.

1. Open **System Settings → Privacy & Security → Full Disk Access**.
2. Add the `ClaudeRunner.app` path printed by the installer, usually `/Applications/ClaudeRunner.app`.
3. Re-run `bash scripts/setup-mac2.sh`.

If macOS shows the executable path, it should now be
`/Applications/ClaudeRunner.app/Contents/MacOS/ClaudeRunner` when the system Applications folder
is writable, or `~/Applications/ClaudeRunner.app/Contents/MacOS/ClaudeRunner` as a fallback. The installer also keeps a
`Contents/MacOS/run` shim for older launchd entries.

## Verify the fleet
```bash
cd ~/Documents/beethoven/claude-orchestrator/runner
python3 fleet_doctor.py --brief
python3 fleet.py     # should list BOTH hosts as live
```
Or SQL: `select hostname, active_tasks, last_seen from runner_heartbeats
         where last_seen > now() - interval '180 seconds';`

## Control Mac 2 from Mac #1
Once Mac 2 is heartbeating, you should not need to touch its terminal for normal updates:

```bash
cd ~/Documents/beethoven/claude-orchestrator/runner
python3 fleetctl.py status
python3 fleetctl.py pull all       # git pull --ff-only on every live Mac, then restart
python3 fleetctl.py reload all     # reload shared config without a code pull
python3 fleetctl.py restart all    # graceful runner restart via keepalive
python3 fleetctl.py set MAX_PARALLEL 4
```

## What each machine does automatically
- Pulls the highest **priority × ROI** work first (economic scheduler in `db.claim_task`).
- Throttles itself on RAM/disk (`resource_governor`) — independently per machine.
- Honors the **global kill switch** and the **real-$ circuit breaker** (shared via the DB / per-machine
  call budget), so adding a machine cannot blow the spend caps.
- Polls central `fleet_config` / `fleet_control`, so shared config, git-pull, reload, and restart
  commands converge without per-Mac prompting.

## When you actually want cloud
Add cloud when you need **N>2**, want 24/7 capacity independent of your Macs being awake, or want a
machine geographically closer to a provider. The migration is the same five steps on a Linux box. Until
then, N=2 on your two Macs is free and sufficient.
