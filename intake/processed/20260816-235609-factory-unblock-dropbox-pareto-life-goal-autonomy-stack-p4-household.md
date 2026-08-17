PROJECT: beethoven

- id: factory-unblock-dropbox-pareto-life-goal-autonomy-stack-p4-household
  title: Unblock dropbox-pareto-life-goal-autonomy-stack-p4-household-legal-doc-updater-notificat (stuck CONFLICT)
  material: no
  proof: npm --prefix packages/darwin-kernel run test
  prompt: |
    Task 'dropbox-pareto-life-goal-autonomy-stack-p4-household-legal-doc-updater-notificat' has been stuck in state CONFLICT for over 60 minutes. Recorded note: train: still conflicts after 4 redos - needs manual rebase. Conflicting files: runner/agentic_coders.py
    runner/benchmark_redlines.py
    runner/foulkon_sync.py
    runner/keepalive.sh
    runner/lane_guard.py
    runner/legal_docket.py
    runner/runner.py
    runner/slo_controller.py
    runner/tests/test_lane_guard.py.
    
    Diagnose the root cause (build failure, merge conflict, flaky test, or a genuine blocker needing a design decision) and fix it, or if it's a duplicate/obsolete task, close it with a reason. Do not just retry blindly — read the actual error.
