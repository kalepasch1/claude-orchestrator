
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

## Git identity (required — read before committing)

All commits in this repo MUST be authored as the repo owner:

    git config user.name "kalepasch1"
    git config user.email "kalepasch@gmail.com"

Run this immediately after cloning, before your first commit. Vercel blocks
production deployments whose commit author is anyone else — commits authored
as e.g. mandyjustinepasch@gmail.com or kale@heretomorrow.us end up in BLOCKED
state and never deploy. Do not use your platform account identity.


## Learned from merged work (auto)
Here are the concise conventions and DO/AVOID rules extracted from the codebase:

**CONVENTIONS:**

* Consistent use of spaces around operators and inside comments.
* Use of descriptive variable names, e.g., `HIVEMIND_APPS` instead of `apps`.
* Consistent naming conventions for types, functions, and interfaces.
* Use of `as const` to assert the type of an array.

**DO/AVOID RULES:**

* DO:
	+ Avoid using magic numbers; use constants or enums instead.
	+ Use meaningful variable names that indicate their purpose.
	+ Ensure consistent coding style throughout the codebase.
* AVOID:
	+ Deep nesting in functions; refactor to reduce complexity.
	+ Unnecessary checks and conditions; simplify logic where possible.
	+ Excessive use of nested loops; consider alternative algorithms.


## Learned from merged work (auto)
Here are the conventions that this codebase follows and the DO/AVOID rules a future agent should respect:

**CONVENTIONS:**

* Use of `.github/workflows/auto-sync.yml` as a single source of truth for automating workflows.
* Consistent use of `actions/checkout@v4` and `actions/checkout` in GitHub Actions workflows.
* Use of `fetch-depth: 0` to fetch all branches, making it easier to manage dependencies.

**DO/AVOID RULES:**

* Avoid duplicating code in multiple commits. This can be achieved by extracting common functionality into separate files or functions.
* Refactor the `auto-sync.yml` file to improve readability and maintainability. For example, consider breaking up long lines into shorter ones or using a consistent naming convention for variables and functions.
* Consider implementing additional checks or validations in the GitHub Actions workflow to ensure that all necessary dependencies are met before proceeding with the automation process.
