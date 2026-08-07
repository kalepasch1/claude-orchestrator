
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

## Incidents

- [2026-08-06 release pipeline recovery](docs/incidents/2026-08-06-release-pipeline-recovery.md) — read before changing `release_train.py` or the merge train.

## Linting

Convention linting ensures CLAUDE.md patterns are enforced before commit. Phase 1 focuses on 3 core rules:

1. **Fail-soft error handling**: Public functions must return sensible defaults on error, not raise on bad input
2. **Hardcoded secrets**: Config keys must not contain PASSWORD|TOKEN|SECRET without env-var indirection
3. **Module-level singletons**: Functions delegate to singleton instances (acquire() → _pool.acquire()), not instance methods

See `CONVENTION_LINT.md` for full rule definitions and examples. Pre-commit hook runs automatically; use `# noqa: RULE_NAME` to skip specific lines.

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


## Learned from merged work (auto — lease-RPC night, 2026-07-29; recovered 2026-08-05)

Recovered from `hotfix/stash-rescue-1785390774-5f879035` (the anonymous-stash sweep of the
lease-RPC night). Re-applied **with judgment, not verbatim**: two rules in the original
auto-distilled block contradicted governing conventions already stated in this file and
have been corrected in place. The correction is noted inline so the distiller does not
re-emit the same advice next pass.

### Conventions the branch-lease code actually follows

- Consistent module naming (e.g. `branch_lease.py`) for files and modules.
- Comments are sparse but load-bearing — they explain *why* a fail-soft path exists,
  not what the line does.
- Descriptive variable names; functions stay short and single-purpose.

### DO / AVOID

- **DO** name magic numbers. The lease code carries bare literals (e.g. the `91`-second
  staleness bound) inline; lift these to module constants or `ORCH_`-prefixed env vars so
  they are fleet-pushable via `fleet_control.py`.
- **DO** keep one coding style. Indentation is already consistent; spacing around
  operators is not.
- **DO** add automated tests for any new lease/heartbeat path — the sweep that lost this
  work went unnoticed precisely because nothing asserted on it.
- **AVOID** *unlogged* broad excepts. **Corrected:** the original block said to avoid
  `except Exception as e` outright. That is wrong here — broad catches are the documented
  *fail-soft error handling* convention of this repo (errors must not wedge the runner).
  The real rule is narrower: a broad catch must write a diagnostic before it swallows, as
  `branch_lease` already does with its `heartbeat RPC infra error (...); fail-soft ALIVE`
  line. A silent `except Exception: pass` is the defect; a logged one is the convention.
- **AVOID** *undocumented* module-level state. **Corrected:** the original block flagged
  the module-level `db` handle as a global to remove. That is also the documented
  convention — *module-level singleton pattern*, where module functions delegate to one
  thread-safe instance. The real rule is that such a singleton must carry a docstring
  saying what it is and how it is initialised, not that it must be eliminated.
