#!/bin/bash
set -e
cd "$(dirname "$0")"

# Clean stale locks
rm -f .git/index.lock .git/HEAD.lock

# Stage everything
git add -A

# Commit
git commit -m "feat: 19 intelligence systems — batch 2+3 integration

Batch 2 (9 modules + integration + tests):
- retry_budget: adaptive retry limits from historical success rates
- error_taxonomy: classify errors, select targeted remediation
- prompt_compressor: deduplicate and compress prompts (4-step pipeline)
- fleet_topology: hardware-aware task routing
- prompt_evolution: self-improving prompt structure
- pattern_adversary: adversarial testing of compiled patterns
- predictive_queue: speculative task generation (default OFF)
- pattern_transfer: cross-project pattern sharing
- CI pipeline (GitHub Actions)

Batch 3 (10 modules + integration + tests):
- semantic_merge: AST-level merge before conflict deferral
- model_cascade: cost-aware model selection with escalation
- test_oracle: incremental test mapping for selective runs
- output_distiller: extract reusable recipes from successful agents
- branch_speculator: fork 3 strategies, pick winner (default OFF)
- fleet_rebalancer: live worker redistribution across projects
- rollback_chain: auto-bisect + revert + requeue regressions
- conversation_memory: compressed transcript passing between retries
- prompt_ab_test: systematic prompt variant A/B testing
- flaky_test_healer: quarantine flaky tests from merge-blocking

All modules: lazy imports, env-var gated (ORCH_*), fail-soft.
runner.py: 19 new hook points across pre-exec, post-exec, error, idle.
queue_preopt.py: 10 new stages (now 22 total).
Tests: 45 new tests (all passing)."

# Push
git push origin master

echo "Done — committed and pushed."
