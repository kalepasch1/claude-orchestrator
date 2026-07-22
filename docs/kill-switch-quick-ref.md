# Kill Switch — Quick Reference

## Purpose
`runner/kill_switch.py` provides a fast, fail-safe mechanism to halt task
claiming on a per-host or fleet-wide basis without killing the runner process.

## How It Works
The kill switch is checked at the top of every runner loop before claiming new
tasks. When active, the runner skips claiming but continues its heartbeat and
control-plane polling, so it can be resumed remotely.

## Activation
- **Fleet-wide**: insert a `fleet_control` row with `action='pause'`,
  `target='all'`.
- **Per-host**: insert with `target='<hostname>'`.
- **Resume**: insert `action='resume'` targeting the same scope.

## Integration with Fleet Control
`fleet_control.py` translates pause/resume control rows into kill-switch state.
The runner calls `kill_switch.is_active()` each loop — if true, it logs the
reason and sleeps until the next iteration.

## Design Notes
- Fail-soft: if the kill-switch check itself errors, claiming proceeds (the
  runner must not wedge on a read failure).
- Host scope uses `socket.gethostname()` for targeting.
