# Remediation Cap

## Purpose
Limits the number of automatic retry cycles for a failing task before
it is escalated to the agentic coder (Claude) for direct implementation.

## Default Cap
3 attempts. After 3 failed remediation cycles, the task prompt includes:
> Remediation cap 3 reached. Do not buffer this task; complete the
> implementation through the agentic coder and make the checks green.

## Behavior After Cap
- The executor must implement the task to completion — no analysis-only
  or plan-only commits.
- If the branch/worktree is missing, reconstruct from the original
  acceptance intent.
- If tests fail, fix them rather than re-queuing.
