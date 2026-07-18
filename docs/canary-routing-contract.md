# Canary Task Routing Contract

Canary tasks validate that the coder-routing pipeline (preflight → planner → coder → QA)
produces a mergeable commit for a given model route. They are generated from historical
merged tasks and intentionally constrained:

## Scope rules

- One tiny, safe improvement: doc clarification, test hygiene, or trivial code cleanup.
- Must not duplicate the original merged feature.
- Must not touch: secrets, dependencies, package managers, billing, legal copy, or
  product behavior.

## Routing fields

| Field          | Purpose                                              |
|----------------|------------------------------------------------------|
| `force_coder`  | Pin the coder model (e.g. `xai`, `openai`, `local`). |
| `kind`         | Always `canary`.                                     |
| `confidence`   | Inherited from the historical task's merge signal.   |
| `base_branch`  | Defaults to `project.default_base` (usually master). |

## Success criteria

A canary passes when the executor commits and pushes a branch that the merge-train
can auto-merge without test failures. The merge-train treats canary branches identically
to regular `agent/*` branches — no special handling.

## Failure handling

If a canary fails (BLOCKED or QUARANTINED), the routing score for its `force_coder`
model is decremented in `qpd_scores`, nudging future routing away from that model for
similar task classes.
