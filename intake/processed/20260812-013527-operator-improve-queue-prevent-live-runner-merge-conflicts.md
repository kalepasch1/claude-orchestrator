PROJECT: beethoven

- id: improve-queue-prevent-live-runner-merge-conflicts
  title: improve-queue-prevent-live-runner-merge-conflicts
  material: no
  model: 
  submitted-by: Codex operator-directed remediation
  depends: []
  proof: runner/tests/test_runner_conflict_free.py and new isolated-promotion regression tests pass; a synthetic bad resolution leaves the live checkout and running commit unchanged.
  prompt: |
    Move automated conflict resolution out of the live writer checkout into an isolated worktree. Layer compatible behavior from both sides, require an exact conflict-marker scan plus Python compile/import smoke and affected tests, and promote the result atomically only after validation. On failure, preserve both refs and quarantine the merge without changing runner.py. Add regression coverage proving a failed resolution cannot plant markers in the live runner.
    
    Queue context: The immediate runner markers are resolved; this task removes the mechanism that allowed invalid merged code to crash-loop the live runner.
