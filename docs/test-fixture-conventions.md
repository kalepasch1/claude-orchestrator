# Test Fixture Conventions

## Purpose

Keep test helpers consistent across the `tests/` directory so new
canary, build, and bugfix tasks can add tests without reinventing
common setup.

## Standard Fixtures (pytest)

| Fixture | File | Description |
|---------|------|-------------|
| `env_minimal` | `test_bootstrap_runner.py` | Minimal Supabase creds dict |
| `mock_supabase` | (shared) | Patches `curl` responses for Supabase API |

## Naming Rules

- Test files: `test_<module>.py` — mirror the runner module name.
- Fixtures: lowercase snake_case, prefixed with the resource they
  mock (e.g., `db_connection`, `env_minimal`).
- Marks: use `@pytest.mark.slow` for anything that spawns a
  subprocess or hits the network.

## Adding a New Test

1. Create `tests/test_<module>.py`.
2. Import shared fixtures from `conftest.py` (create one if absent).
3. Keep each test focused on a single behavior; prefer many small
   tests over few large ones.
4. Assert expected side-effects (file writes, SQL calls) via mocks
   rather than checking stdout.

## Running

```bash
pytest tests/ -v --tb=short
```

Use `-k <pattern>` to run a subset during development.
