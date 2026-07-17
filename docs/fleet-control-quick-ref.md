# Fleet Control — Quick Reference

## Purpose
`runner/fleet_control.py` is the N-machine coordination gateway. It closes the
gap between shared-queue runners so the entire fleet is configurable from one
place (Mission Control / the DB) without touching a second terminal.

## Three Pillars

### 1. Central Config
`fleet_config` key/value rows are loaded into `os.environ` every loop on every
machine. Change `MAX_PARALLEL`, `ORCH_EXTRA_CODERS`, or any `ORCH_*` knob once
and all Macs converge. Only safe (non-secret) keys are applied.

### 2. Central Control
`fleet_control` rows carry actions (`restart`, `git_pull`, `reload_config`,
`pause`, `resume`) targeted at a hostname or `'all'`. Each machine acks into
`handled_by`. Pause is soft/keepalive-safe — the runner stops claiming but
stays resident; resume lifts it on the next loop.

### 3. Auto-Update
With `ORCH_AUTO_PULL=true`, each machine periodically runs
`git pull --ff-only`, so a push from any machine propagates fleet-wide.

## Design Notes
- Pure DB + git; no model spend.
- Fail-soft: any error is swallowed so it can never wedge the runner.
- Secrets/credentials are never pushed through `fleet_config`.
