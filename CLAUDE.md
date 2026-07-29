
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
Here are the extracted conventions and DO/AVOID rules:

**CONVENTIONS:**

* Use clear and concise language in decision-making documents.
* Include a date, status, and proof hash for each decision.
* Define key terms and acronyms used throughout the document.
* Organize content in a logical and consistent manner.

**DO/AVOID RULES:**

* Avoid using ambiguous or unclear language that may lead to misinterpretation.
* Do not introduce new risks or uncertainties without proper mitigation strategies.
* Use conditional language (e.g., "we conditionally support this proposal") instead of absolute statements.
* Refrain from including confidential information in publicly accessible documents.

## No-network agent sessions (ChatGPT sandbox)

ChatGPT's code sandbox has no outbound network — `git push` and DNS always fail
there. Do not debug it. Emit a patch instead: see [CHATGPT.md](./CHATGPT.md).

## ChatGPT / no-network sandbox handoff (2026-07-27)

ChatGPT's code-execution sandbox has **no outbound network** — `git push` and DNS
(`Could not resolve host: github.com`) fail there permanently. It is a platform
limitation; do not debug it. Sandbox sessions emit a **patch**; this Mac pushes.

**Bridge:** `tools/chatgpt-bridge/` (see its README).
Drop `<repo>--<slug>.patch` (or `.diff`/`.zip`/`.tar.gz`) into
`~/Documents/chatgpt-dropbox/` → within 30s it becomes an isolated worktree, a commit
authored `kalepasch1 <kalepasch@gmail.com>`, a `chatgpt/<slug>` branch, and a PR.
Results in `_applied/` / `_failed/`; log at `_logs/bridge.log`. CLI: `chatgpt-patch <file>`.

- launchd agent `com.claudeorchestrator.chatgptbridge` runs **through ClaudeRunner.app**
  — launchd cannot read or execute anything under `~/Documents` without that FDA grant.
  The app launcher now accepts `.sh` jobs relative to repo root.
- **FDA loss is self-reporting.** If the grant goes, the watcher can neither run nor
  complain (its own file becomes unreadable), so `com.claudeorchestrator.chatgptbridge.watchdog`
  runs every 5 min from `~/Library/Application Support/chatgpt-bridge/` — outside
  `~/Documents` on purpose — and notifies when the heartbeat at
  `~/Library/Logs/claude-orchestrator/chatgpt-bridge.heartbeat` is >10 min stale.
  `install.sh` verifies the chain end-to-end and fails loudly if the grant is missing.
- Browser fallback in every repo: Actions → **Apply ChatGPT patch** → paste
  `git diff | base64`. Needs "Allow GitHub Actions to create and approve pull requests"
  (enabled on all six repos).
- Every repo carries `CHATGPT.md` telling the agent to emit a patch instead of pushing;
  `deploy-to-repos.sh` (re)installs it plus the workflow everywhere.
- Direct pushes to production branches are still blocked by `production_push_guard` —
  the bridge opens PRs, it does not bypass the release train.


## Learned from merged work (auto)
### Conventions Followed by the Codebase:

* The code uses a consistent naming convention (e.g., `branch_lease.py`) for files and modules.
* The use of comments is sparse but useful, providing context for complex sections of code.
* Variable names are descriptive, although some could be improved for better readability.
* Functions are well-structured and concise, making it easy to follow their logic.

### DO/AVOID Rules for a Future Agent:

* **AVOID**: Using magic numbers directly in the code (e.g., `91` in `except Exception as e: sys.stderr.write(f"[branch_lease] heartbeat RPC infra error ({e}); fail-soft ALIVE\n")`). Consider defining constants or enums to make the code more readable and maintainable.
* **DO**: Use a consistent coding style throughout the codebase. The provided diffs seem to follow a consistent indentation style, but other aspects of style (e.g., spacing around operators) are not consistently applied.
* **AVOID**: Relying on global variables or functions without proper documentation. In this case, `db` is used as a global variable without explanation.
* **DO**: Implement automated testing for the codebase to ensure its correctness and reliability.
* **AVOID**: Using bare `except` clauses (e.g., `except Exception as e`). Consider using more specific exception handling to catch only the expected errors.
