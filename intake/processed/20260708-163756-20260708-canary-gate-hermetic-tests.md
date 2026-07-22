PROJECT: beethoven

- id: relfix-hermetic-canary-gate-tests
  title: Make runner/tests hermetic so self_deploy's canary gate is deterministic
  material: yes
  model: opus
  depends: []
  proof: `python3 -m pytest runner/tests -q -x` exits 0 when run twice consecutively
  prompt: |
    self_deploy.canary_gate requires `python3 -m pytest runner/tests -q -x` rc==0 before any
    cooperative restart — but several tests read LIVE state (Supabase queue counts via db.py's
    auto-loaded runner/.env, real machine RAM via local_model_slots, live ollama process state),
    so the gate fails nondeterministically and self-deploys stall for days. Observed flaky/failing
    today (different failures on consecutive runs): test_drain_policy.py (auto_mode_uses_queue_floor
    and siblings — reads live queue), test_model_routing.py (agentic_easy_work_can_route_to_non_claude,
    agentic_coders_auto_register_paid_and_local_backends, agentic_material_work_can_use_paid_credits —
    read real RAM/headroom + gateway availability), test_owner_decision_model.py TestSweep
    (sweep_only_touches_legal_gated), test_routing_intelligence.py
    (coder_canary_prefers_historical_merged_prompt).
    Fix by injection, not deletion: every test must stub its inputs (patch db.select/count, patch
    local_model_slots.ram_gb/is_heavy, patch heavy-running counts, set explicit env with
    patch.dict(clear-ish)) so the suite passes on ANY machine regardless of queue depth, RAM, or
    loaded models. Add a conftest.py guard that fails any test performing a real network call to
    Supabase (monkeypatch db._req to raise unless explicitly whitelisted by an integration marker).
    Do NOT weaken assertions — make inputs deterministic. Run the full suite twice back-to-back in
    the proof to demonstrate stability.

OPERATOR:
  - Mac 2 (Mandy's runner) must `git pull origin master` in the orchestrator repo and restart its runner to pick up today's fixes (branch-share push, remote-aware sweeper, merge-train blockade fix, heavy-ollama exclusion). Nothing auto-pulls on Mac 2 — until then it still files false missing-branch recoveries.
