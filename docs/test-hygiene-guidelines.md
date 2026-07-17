# Test Hygiene Guidelines

Standards for maintaining test quality across the orchestrator codebase.

## Naming conventions

- Test files: `tests/<module-name>.test.js`
- Describe blocks: match the exported function or module name
- It blocks: start with a verb — "returns", "throws", "handles", "ignores"

## Isolation rules

- No shared mutable state between tests
- Each test creates and tears down its own fixtures
- Use seedable RNG (`mulberry32`) for any stochastic test
- No snapshot tests — they require manual review on every change

## Coverage expectations

- New engine: ≥20 test cases covering normal, edge, and error paths
- Bug fix: add a regression test reproducing the bug before fixing
- Refactor: existing tests must stay green without modification
