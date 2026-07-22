
## Operator workflow (manual, not auto-distilled)

Routine strategic/objective prompts belong in the operator drop-box, not a manual serial
session: drop a `PROMPT-<name>.md` file at repo root (or a canonical-format file in `intake/`)
and `intake_watcher.py` auto-decomposes anything that isn't already canonical format through
`planner.py`'s contract-first DAG and queues it for parallel, dependency-linked execution (see
`prompt_factory.py` and the drop-box section of `intake_watcher.py`'s module docstring).

A manual serial Claude Code session (an operator pasting a long prompt directly into a live
session, working the phases by hand) is reserved for **fleet-down recovery only** — i.e. when
the fleet itself can't queue or execute anything yet, so there's nothing for intake to route
work to. Once the fleet is healthy, prefer the drop-box.

## Learned from merged work (auto)

**CONVENTIONS**

*   Centralized configuration management: fleet-wide config changes go through a central `fleet_config` table and are applied to all machines via an in-process gateway (`fleet_control.py`).
*   Safe config keys only: only config keys without secrets or credentials can be pushed fleet-wide.
*   DB + git for synchronization: code updates are propagated between machines using git, and database operations are used for configuration management.
*   Fail-soft error handling: errors during code execution or database queries do not wedge the runner; they are swallowed to prevent crashes.

**DO/AVOID RULES**

*   **DO** prefix config key changes with ORCH_ to make them fleet-wide applicable.
*   **DO NOT** introduce hardcoded secrets or credentials in the configuration keys.
*   **AVOID** using manual SSH or second-terminal steps for configuration management; use the centralized gateway (`fleet_control.py`) instead.
*   **AVOID** introducing model-specific logic that can wedge the runner on errors; instead, use fail-soft error handling.

## Learned from merged work (auto)

**CONVENTIONS**

- **Module-level singleton pattern**: Provide module-level functions that delegate to a thread-safe singleton instance (e.g., `acquire()` → `_pool.acquire()`); avoids passing state through call chains
- **Fail-soft error handling**: Return empty string `""` or sensible defaults on any error; never raise on bad input (None, missing path, permission errors)
- **Environment variable configuration**: All tunable parameters (pool size, TTL, limits) are env vars with sensible defaults, not hardcoded
- **Thread-safe with explicit locks**: Protect shared state with `threading.Lock()`; minimize critical section, do disk I/O outside the lock
- **Defensive file I/O**: Check multiple file locations, use `errors="replace"`, catch `FileNotFoundError` separately, truncate at a byte limit

**DO/AVOID RULES**

- **DO** include 20+ test cases covering normal paths, edge cases (None, empty string, bad paths), eviction, staleness, and memory pressure before merging
- **AVOID** forcing callers to handle unavailability—design for graceful degradation (missing file → return `""` instead of raising)
- **DO** gate resource expansion (new pool entries) on memory checks via `resource_governor.can_claim()` to prevent wedging under pressure
- **AVOID** blocking the caller on slow I/O—if a cache miss is likely, accept it and fall back rather than synchronous disk waits
- **DO** provide `stats()` and `invalidate()` methods so operators and tests can observe/control pool state

## Worktree convention (auto-distilled)

All agent work happens in isolated git worktrees under `{repo}-wt/{slug}`, never via
`git checkout` in the main repo checkout. `sentinel.py` monitors the main checkout and
will stash+reset any non-base branch it finds there. Worktrees are removed after push;
the `agent/{slug}` branch persists for merge-train pickup.
