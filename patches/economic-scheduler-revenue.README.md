# economic-scheduler-revenue — recovered patch (ready, not applied)

Located/reconstructed 2026-08-06 per backlog-batch-beethoven-e63dfee
(locate-and-prepare step; the apply step is a separate task).

## Findings

- Prior attempt branches (`7371e3f-implement-economic-scheduler-revenue-*`,
  `a86bb21-recover-economic-scheduler-revenue-*`) contain only 4-line stub
  .txt files — no recoverable patch content.
- `origin/agent/economic-scheduler-revenue` is fully merged into master
  (empty diff); the module `runner/economic_scheduler.py` and its suites
  are on master already.
- The actual stale gap: 3 of 28 revenue tests fail on origin/master because
  `REVENUE_KEYWORDS` uses bare nouns (`payment`, `pricing`, `stripe`) and
  over-triggers the 1.5x revenue boost on incidental mentions.

## The patch

`economic-scheduler-revenue.patch` — switches `REVENUE_KEYWORDS` to intent
phrases (`payment integration`, `payment processing`, …). Verified:

- `git apply --check` passes against origin/master (this branch's base)
- applied in a scratch worktree: revenue suite 28/28 green (was 25/28)
- also committed as branch `agent/backlog-batch-beethoven-7c38d4c`

Build env note: repo is stdlib-Python; `python3 -m pytest` runs directly —
no `make build` step exists, nothing to install.
