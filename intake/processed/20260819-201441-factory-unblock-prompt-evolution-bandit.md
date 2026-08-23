PROJECT: beethoven

- id: factory-unblock-prompt-evolution-bandit
  title: Unblock prompt-evolution-bandit (stuck CONFLICT)
  material: no
  proof: npm --prefix packages/darwin-kernel run test
  prompt: |
    Task 'prompt-evolution-bandit' has been stuck in state CONFLICT for over 60 minutes. Recorded note: train: still conflicts after 4 redos - needs manual rebase. Conflicting files: runner/prompt_evolver.py.
    
    Diagnose the root cause (build failure, merge conflict, flaky test, or a genuine blocker needing a design decision) and fix it, or if it's a duplicate/obsolete task, close it with a reason. Do not just retry blindly — read the actual error.
