PROJECT: claude-orchestrator

# ROOT-CAUSE REMEDIATION. Audit (in Supabase table cowork_activation_audit) found ~180/486 runner
# modules unreferenced and 5 safety/self-improve gates built-but-not-wired. Cause: the intake proof
# contract ("pytest exits 0") is satisfiable by a module + its own unit test with ZERO wiring.
# TASK 1 fixes the contract; EVERYTHING here depends on it so nothing orphans again.
# Every proof below is an INTEGRATION/REACHABILITY proof (the gate must actually FIRE), not unit-only.

- id: reachability-contract
  title: Redefine "done" as reachable-and-live, not just tests-pass
  material: yes
  model: opus
  depends: []
  proof: `python3 -m pytest runner/tests/test_reachability_contract.py` exits 0
  prompt: |
    Add runner/reachability.py `is_reachable(module) -> {reachable, via, flag_on}` that returns true only if
    the module is imported by a live entrypoint OR registered in runner.py/periodic.py/supervisor.py OR invoked
    by a hook/script/workflow, AND (if it declares an env/DB flag) the flag is ON. Wire it into the merge/verify
    path (runner.py + intake_compiler.py): a task whose diff adds a new runner module that is NOT reachable
    FAILS the merge (routed back as 'needs-wiring'), and intake_compiler augments every generated task's proof
    with a reachability assertion. Add runner/tests/test_reachability_contract.py: an orphan module fails the
    check; a wired/flag-on module passes; a flag-off module fails.

- id: wire-merge-invariant-firewall
  title: Actually run the merge-invariant firewall on every merge (flag ON)
  material: yes
  model: sonnet
  depends: [reachability-contract]
  proof: `python3 -m pytest runner/tests/test_firewall_fires.py` exits 0
  prompt: |
    merge_invariant_firewall.py is imported only by its own test and gated ORCH_MERGE_FIREWALL_ENABLED=OFF.
    Call its checks in the real merge path (runner.py merge / approval_merge.py) BEFORE any merge, and default
    the flag ON (or remove the gate). Add runner/tests/test_firewall_fires.py: a diff that DROPs an RLS policy,
    flips a settlement/money-movement default, or removes a transfer token-gate is BLOCKED and routed to human;
    a benign diff passes. Compose with (do not replace) the existing build gate.

- id: wire-premerge-redteam
  title: Run the adversarial red-team gate before judge.py
  material: yes
  model: sonnet
  depends: [reachability-contract]
  proof: `python3 -m pytest runner/tests/test_redteam_fires.py` exits 0
  prompt: |
    premerge_redteam.py says it "runs BEFORE judge.py" but nothing calls it. Invoke it in runner.py immediately
    before the judge step; a finding above severity blocks + routes to human. Add runner/tests/test_redteam_fires.py:
    a planted prompt-injection / auth-bypass diff is caught; a clean diff passes.

- id: wire-quality-gate
  title: Enforce quality_gate in the autonomous merge path
  material: yes
  model: sonnet
  depends: [reachability-contract]
  proof: `python3 -m pytest runner/tests/test_quality_gate_fires.py` exits 0
  prompt: |
    quality_gate.py ("raise the bar on tests-pass before an autonomous merge") has no caller. Wire it into the
    merge path after tests + before merge. Add runner/tests/test_quality_gate_fires.py: a diff that passes tests
    but fails the quality bar (e.g. no new tests for changed logic / coverage drop) is HELD; a good diff merges.

- id: wire-provenance-on-merge
  title: Record a signed provenance row on every autonomous merge
  material: yes
  model: sonnet
  depends: [reachability-contract]
  proof: `python3 -m pytest runner/tests/test_merge_provenance.py` exits 0
  prompt: |
    provenance.py (merge-provenance ledger) is imported only by its test. Call it on every merge to write a
    signed {commit, task, why, proof_result, approver|policy, model, cost} row. Add
    runner/tests/test_merge_provenance.py: a merge produces a verifiable row; tampering fails verification.

- id: enable-eval-harness-selfimprove
  title: Turn on the self-improvement regression gate + wire causal_attribution
  material: yes
  model: opus
  depends: [reachability-contract]
  proof: `python3 -m pytest runner/tests/test_selfimprove_gate.py` exits 0
  prompt: |
    TASKS.md has an unchecked "[ ] Enable eval_harness.py"; REPORT-meta-optimizer.md:164 notes causal_attribution
    has "zero references currently". In the self-improvement path (self_review.py / feedback_review.py), require
    a candidate change to be A/B'd via eval_harness on held-out tasks BEFORE adoption, and wire causal_attribution
    into eval_harness so realized impact is attributed. Add runner/tests/test_selfimprove_gate.py: a regressing
    candidate is rejected; an improving one is adopted; attribution is recorded.

- id: close-scoreboard-kpi-loop
  title: Create the scoreboard table + close the KPI learning loop into prompt_factory
  material: yes
  model: opus
  depends: [reachability-contract]
  proof: `python3 -m pytest runner/tests/test_kpi_loop.py` exits 0
  prompt: |
    prompt_factory.py:17 — "KPI gaps from the scoreboard: NOT wired in yet — the scoreboard table doesn't exist".
    Create the scoreboard table (migration) + have scoreboard_data/scoreboard_metrics populate it, then wire
    prompt_factory to read KPI gaps and emit remediation tasks. Add runner/tests/test_kpi_loop.py: a seeded KPI
    gap produces a queued remediation task.

- id: activation-telemetry-kpi
  title: Runtime reachability telemetry + fleet activation KPI (the headline metric)
  material: no
  model: sonnet
  depends: [reachability-contract]
  proof: `python3 -m pytest runner/tests/test_activation_kpi.py` exits 0
  prompt: |
    Add lightweight execution counters (module -> last_executed_at, exec_count_7d) written by the scheduler/
    dispatcher, into a module_reachability table. Add an aggregator computing the fleet ACTIVATION KPI =
    % of merged modules reachable AND executed in the last 7 days. Backfill from the existing
    cowork_activation_audit findings. Expose for the dashboard. Add runner/tests/test_activation_kpi.py for the
    counter + aggregate math. Target: drive activation 63% -> 95%.

- id: flag-debt-burndown
  title: Decide every default-OFF flag; enable the safe throughput ones behind a canary
  material: yes
  model: sonnet
  depends: [activation-telemetry-kpi]
  proof: `python3 -m pytest runner/tests/test_flag_debt.py` exits 0
  prompt: |
    Produce a report of every default-OFF flag (parallel_dispatch, work_stealer, task_fusion, predictive_queue,
    queue_preopt, tdd_gate, chaos, merge firewall, etc.) with owner + decision date. Enable the low-risk
    throughput multipliers (parallel_dispatch, work_stealer, task_fusion, predictive_queue, queue_preopt) behind
    a canary with auto-rollback on error-rate/cost regression; leave safety flags (tdd_gate, firewall) ON via the
    wiring tasks above. Add runner/tests/test_flag_debt.py: the report enumerates flags; enabling is canary-gated.

- id: module-inventory-index
  title: Inject a live module index into the planner so it reuses instead of rebuilding
  material: no
  model: sonnet
  depends: [reachability-contract]
  proof: `python3 -m pytest runner/tests/test_inventory_reuse.py` exits 0
  prompt: |
    Generate a live index {module, one-line purpose, reachable?} from the runner tree + reachability.py and inject
    it into planner.py/prompt_factory.py so a new proposal that duplicates an existing capability (e.g. another
    canary/bandit/promotion variant) is flagged to REUSE the existing module. Add runner/tests/test_inventory_reuse.py:
    a duplicate-capability proposal is matched against an existing module and down-ranked/merged.

- id: docs-as-tests
  title: Fail CI when README/HANDOFF claims a capability that isn't reachable
  material: no
  model: sonnet
  depends: [reachability-contract]
  proof: `python3 -m pytest runner/tests/test_docs_as_tests.py` exits 0
  prompt: |
    Documentation drift is what hid the dead gates for weeks. Add a test that parses capability claims from
    README.md / HANDOFF-*.md / memory/glossary.md and asserts each named module is reachable (via reachability.py).
    Add runner/tests/test_docs_as_tests.py: a claimed-but-orphaned module fails the test.

- id: requeue-cade-repeal-compliance
  title: Re-land the CADE risk-bands + instant-repeal isolation + compliance-as-tests under the new contract
  material: yes
  model: opus
  depends: [reachability-contract, wire-merge-invariant-firewall, wire-provenance-on-merge]
  proof: `python3 -m pytest runner/tests/test_cade_bands.py runner/tests/test_isolation_harness.py` exits 0
  prompt: |
    The 0705 tasks (intake/processed/*cade-repeal*, apparently/tomorrow compliance-as-tests) were ingested but
    never wired (they'd be orphans). Re-implement them UNDER the reachability contract: CADE numeric risk score +
    bands (<50 auto, 50-70 auto+instant-repeal-isolation, >70 human), the repealable_features isolation harness +
    runtime feature_flags + console repeal panel, and the compliance-as-tests merge gate — each with an integration
    proof that the gate/repeal actually FIRES and each module is reachable. See the 0705 files for full specs.

OPERATOR:
  - This runs on the claude-orchestrator repo itself — route to the self-build lane.
  - Enabling throughput flags + the firewall changes autonomous behavior; they're canary/rollback-gated but review the first canary.
  - Cowork cannot push from its sandbox; these need your credentialed runner/CI. The reachability contract makes the pipeline self-verify wiring so you don't have to hand-check each one.
