PROJECT: beethoven

- id: factory-unblock-backlog-batch-beethoven-ccacb00-commit-final-impleme
  title: Unblock backlog-batch-beethoven-ccacb00-commit-final-implementation-commit-documentation (stuck BLOCKED)
  material: no
  proof: npm --prefix packages/darwin-kernel run test
  prompt: |
    Task 'backlog-batch-beethoven-ccacb00-commit-final-implementation-commit-documentation' has been stuck in state BLOCKED for over 60 minutes. Recorded note: cowork-executor-v6.5 BLOCKED — no code target. Task asks to stage and commit "all changed documentation files" on branch backlog-batch-beethoven-ccacb00. Missing: the uncommitted working-tree state the task presupposes. origin/agent/backlog-batch-beethoven-ccacb00 exists and its history is fully committed (HEAD 988649bb); no worktree for it remains, so there are no unstaged doc changes to identify or stage. The task is a git-hygiene instruction scoped to a session that has ended, not a code change. Re-file with specific doc files if the content is still wanted.
    
    Diagnose the root cause (build failure, merge conflict, flaky test, or a genuine blocker needing a design decision) and fix it, or if it's a duplicate/obsolete task, close it with a reason. Do not just retry blindly — read the actual error.
