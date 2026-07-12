---
name: cowork-executor
description: Fast autonomous task executor template for claude-orchestrator. 6 parallel instances (cowork-executor-1 through -6) each claim 3 tasks every 2 minutes via atomic optimistic locking.
---

# Cowork Executor (Parallel Fleet Template)

6 instances run on */2 cron. Each claims 3 tasks, executes directly, reports. Atomic claiming prevents collisions.

Account format: `cowork-executor-{N}` where N=1..6. All accounts start with `cowork-` so orphan detectors skip them.

## Optimizations over v1
- 3 tasks per run (not 10) — faster turnover, more overlapping runs
- Skip tests unless prompt explicitly requires them — merge_train tests later
- 2-min time-box per task (not 3)
- No complexity analysis — just implement what the prompt says
- Each instance has unique account + heartbeat key

## Throughput math
- 6 executors × 3 tasks/run × overlapping runs every 2 min
- If each run takes ~6 min (3 tasks × 2 min): ~3 tasks/executor/6min = 30 tasks/executor/hr
- 6 executors × 30 = ~180 tasks/hr from Cowork alone
- Plus local runner's 40 concurrent lanes = 200+ tasks/hr total
- Target: 4400 task backlog cleared in ~22 hours
