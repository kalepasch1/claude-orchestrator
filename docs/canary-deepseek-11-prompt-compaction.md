# Canary Deepseek-11: Prompt Compaction Behavior

Documents the prompt-size guardrail in `runner/agentic_repair.py`
(`_original_prompt`) to aid future task sizing decisions.

## How compaction works

1. Raw prompt is extracted from the task, stripping any prior
   `AGENTIC-REPAIR DIRECTIVE` marker to prevent double-injection.
2. If the prompt fits within `MAX_PROMPT_CHARS` (default 18 000),
   it passes through unchanged.
3. If it exceeds the limit, it is split into a head (first ~6 000 chars)
   and a tail (remaining budget), joined by a compaction notice that
   instructs the coder to inspect repo files directly.

## Why this matters for canary routing

Oversized prompts can degrade small-model canaries. The compaction
ensures every coder — including local 3B canaries — receives a
prompt within its effective context window.
