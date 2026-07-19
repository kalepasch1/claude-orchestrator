# Canary Routing — Test Hygiene

## Purpose
Canary tasks (`kind=canary`) validate that the coder-routing pipeline
(preflight triage → model selection → prompt assembly → execution) produces
mergeable code across model families (deepseek, ollama, claude, gpt).

## What a canary tests
1. **Prompt decomposition** — parent canary splits into N slices; each must
   produce a commit independently.
2. **Cross-project reuse** — enrichment layers (`cowork_assemble.py`) surface
   prior merged diffs from sibling projects so the executor adapts rather than
   rebuilds.
3. **Routing accuracy** — the `learned route` in the prompt reflects the
   pipeline's model selection; the executor validates it compiles/runs.

## Failure modes to watch
- Hex-only PATCH TEMPLATE stubs with no English intent → quarantine.
- Enrichment returns empty because `prompt_assembler` can't find the slug →
  executor falls back to raw prompt (acceptable, log it).
- Worktree collision when two executors claim slices of the same canary →
  mitigated by unique branch names (`agent/{slug}`).

## Adding a new canary family
1. Insert a parent task with `kind=canary` and the target `project_id`.
2. Runner's `canary_decompose` splits it into slices automatically.
3. Each slice inherits `base_branch` from the parent.
4. After all slices reach DONE/MERGED, the parent auto-promotes.
