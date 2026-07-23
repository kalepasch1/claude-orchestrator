# Activate Design Integration Suite

## Purpose
Activate the design integration suite as part of the orchestrator build pipeline.

## Status

Implemented and wired into the canonical completion path.

## Runtime Map

- `runner/design_sources.py` discovers every tracked Markdown source whose filename
  identifies it as a specification, design, blueprint, architecture, requirements
  document, or ADR. Processed intake, memory, reports, generated task stubs, and
  dependency trees are excluded.
- `runner/planner.py` injects the complete active design contract before decomposition.
- `runner/prompt_assembler.py` injects the same bounded contract into every coder prompt.
- `runner/result_cache.py` includes the design-corpus fingerprint in cache signatures,
  so a source revision invalidates earlier completion results.
- `runner/runner.py` runs the design-source coverage gate before review, autonomy
  shortcuts, and canonical integration. A changed design source cannot complete
  without a corresponding implementation change.
- `runner/parallel_dispatch.py` and `runner/cowork_executor.py` apply the same
  contract before their API/subscription fast paths can mark a task complete.
- Proposed, draft, rejected, superseded, and archived sources remain visible to agents
  as advisory context but do not silently become completion requirements.

## Verification

Run:

```sh
python3 runner/design_sources.py .
python3 -m pytest runner/tests/test_design_sources.py runner/tests/test_prompt_assembler.py
```
