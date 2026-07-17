# Agentic Repair — Flow Overview

`runner/agentic_repair.py` turns task failures into structured repair
contracts instead of blind retry loops.

## How It Works

1. A task fails with a concrete error (test failure, lint error, runtime crash).
2. The repair helper rewrites the task prompt into a repair directive that:
   - Preserves all prior work (no starting from scratch)
   - Reproduces the concrete failure
   - Targets the root cause specifically
   - Runs checks before committing
3. The rewritten task is re-queued with the `AGENTIC-REPAIR DIRECTIVE` marker.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `ORCH_AGENTIC_REPAIR_PROMPT_CHARS` | `18000` | Max chars in repair prompt |

## Design Principle

Failures carry diagnostic context forward. Each repair attempt builds on
the previous one rather than discarding it, so the system converges on a
fix rather than repeating the same mistake.
