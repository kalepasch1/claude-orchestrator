# Test Hygiene Note — cowork_assemble.py

## Coverage Gap

`runner/cowork_assemble.py` lacks unit tests. The module is called by
every cowork executor session (Step 3b) and handles enrichment assembly,
model suggestion, and cross-project hints.

## Recommended Test Cases

1. `--task-id` with missing task → should return empty enriched_prompt
2. Valid task ID → should return enriched_prompt, model, and EV score
3. Missing `--repo-path` → should fail gracefully with stderr message
4. Cross-project hint injection → should include hints from related projects
