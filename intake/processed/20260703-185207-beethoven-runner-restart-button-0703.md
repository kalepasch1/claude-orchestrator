PROJECT: beethoven

- id: runner-remote-restart-control
  title: Runner honors a remote restart request (control row) — self-restart loop
  material: no
  model: sonnet
  depends: []
  proof: python3 -c "import ast; ast.parse(open('runner/runner.py').read())"
  prompt: |
    Add a lightweight remote-control path so a specific runner host can be restarted from Mission
    Control. Use the existing `controls` table (or a new `runner_control` table if cleaner) with a
    row shape: {scope:'runner', target: <hostname or 'all'>, action:'restart', requested_at,
    handled_at}. In runner.py's main loop (near the heartbeat), each cycle check for an UNHANDLED
    restart control whose target matches this host's hostname (socket.gethostname()) or 'all'; when
    found: mark it handled (set handled_at), log it, release the singleton lock cleanly, and exit the
    process (keepalive.sh will respawn a fresh runner). Guard so a handled row is never re-triggered
    (match handled_at is null). Fail-soft: any error in the check must not crash the loop. Keep it
    OFF-by-default safe — only an explicit restart row triggers it. This is runner-only/additive.

- id: mc-restart-runner-button
  title: Mission Control — per-runner "Restart" button
  material: no
  model: sonnet
  depends: [runner-remote-restart-control]
  proof: npm run build
  prompt: |
    In the Mission Control web app (web/), on the runners/health panel that lists runner_heartbeats,
    add a small "Restart" button per runner host. It calls a new server endpoint
    POST /api/runners/restart { host } which inserts a controls row {scope:'runner', target: host,
    action:'restart'} (service client; same pattern as other control endpoints). Show a toast
    "Restart requested — host will respawn within ~1 min". No auth beyond the existing dashboard
    gate. Keep `npm run build` green. This gives one-click recovery for a runner that has gone idle
    (e.g. Mac 2 / Mandys-MBP) without touching the machine.

OPERATOR:
  - None.
