# Canary xAI-12: Repair Category Coverage

Documents the two category sets in `runner/agentic_repair.py` and their
behavioral difference to aid future canary routing decisions.

## TECHNICAL_CATEGORIES (same-task repair)

These categories trigger in-place repair on the original task branch:
`buildfail`, `testfail`, `quality`, `verify`, `judge`, `noop`,
`missing-branch`, `conflict`, `timeout`, `runner-exception`, `capacity`,
`transient`, `orphaned-running`, `stale-merging`, `approval`, `oversized`,
`rework`.

## REPLACEMENT_ONLY_CATEGORIES (new-slug replacement)

These categories create a replacement task with a new slug to avoid
re-introducing the blocked mechanism: `legal`, `secret`, `security`.

The distinction matters for merge-train deduplication: replacement slugs
are new entries, while technical repairs keep the original slug.
