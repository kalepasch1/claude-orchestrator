# Runner Module

The runner module orchestrates task execution and resource lifecycle management for the Beethoven orchestrator.

## Autoclear Policy

This feature automatically clears resources based on rules defined in `runner/autoclear_rules.yaml`. When tasks complete, the autoclear policy evaluates configured rules to determine which resources (volumes, logs, artifacts) should be cleaned up. Supported actions include `delete_volume`, `delete_logs`, and `delete_artifacts`. Rules can be conditional (e.g., only delete logs if `status==completed`) and support rollback semantics — if an action has `rollback: true` and fails, the entire policy operation reports failure.

See `autoclear_rules.yaml` for the rule format and examples.
