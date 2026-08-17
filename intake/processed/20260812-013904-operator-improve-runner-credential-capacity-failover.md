PROJECT: beethoven

- id: improve-runner-credential-capacity-failover
  title: improve-runner-credential-capacity-failover
  material: no
  model: 
  submitted-by: Codex operator-directed remediation
  depends: []
  proof: Account-pool and lane-routing tests pass; simulated expired OAuth and weekly exhaustion move work to a healthy lane without incrementing task failure attempts.
  prompt: |
    Make coder-lane authentication and subscription capacity fail over before work is claimed. Add active credential probes, distinguish weekly-limit exhaustion from expired OAuth and transient provider failures, quarantine only the unhealthy account, route to a verified-capacity account/provider, and pause claiming when no lane is healthy rather than burning task attempts. Surface capacity state, reset time, and required operator action without logging credentials. Add deterministic tests for weekly limit, refresh failure, recovery, all-lanes-down, and task-attempt preservation.
    
    Queue context: Runner logs showed both weekly subscription exhaustion and an OAuth session that could not refresh during the queue outage.
