# Canary GPT-34: Coder Routing Verification

Verifies that the `choose_coder` function in `runner/agentic_repair.py`
correctly falls through from forced → existing model → default coder,
and that `capacity`/`transient` categories always use the default
(non-expensive) repair coder path.

## Observed behavior (canary pass)

- `force_coder` field takes absolute precedence.
- Models named `claude`/`sonnet`/`opus`/`auto` are treated as "unset" and
  fall through to the configured default.
- `_default_coder()` reads `ORCH_REPAIR_CODER` then `ORCH_AGENTIC_REPAIR_DEFAULT_CODER`,
  defaulting to `"ollama"`.
