## Branch flow (enforced — read before pushing anything)

**Every project in this fleet promotes production from its staging branch. Nothing
is pushed to `main`/`master` directly.**

    feature branch  ->  <staging branch>  ->  main / master  ->  Vercel

The staging branch is PER PROJECT: `projects.staging_branch` in the registry,
then `ORCH_STAGING_BRANCH`, then the fleet default `orchestrator/dev`
(`runner/staging_branch.py`). Since 2026-09-10 `smarter` and `apparently-law`
integrate on `dev`; every other project still uses `orchestrator/dev`. The
commands below say `orchestrator/dev`; substitute the project's branch, which
the guard names in its refusal.

Develop wherever you like — `agent/*`, `feat/*`, a worktree, another machine. But
the change has to land on the staging branch before it can reach production, and
that merge is where conflicts get resolved. Resolving them there is the whole
point: it is the one place every in-flight change meets, so the better side can be
kept deliberately instead of whichever branch happened to push last winning by
accident.

`production_push_guard.py` refuses a push to `main`/`master` whose commit is not
contained in `origin/orchestrator/dev`, and prints the four commands that fix it.
The rule is structural and runs before the build and test gates, because a green
build and a green suite say nothing about whether the tree was integrated.

    git fetch origin
    git checkout -B orchestrator/dev origin/orchestrator/dev
    git merge <your-sha>        # resolve conflicts HERE, keeping the better side
    git push origin HEAD:refs/heads/orchestrator/dev
    git push origin <new-dev-sha>:refs/heads/main

Two escape hatches exist and they are deliberately separate switches, so reaching
for one never silently waives the others:

| switch | waives |
|---|---|
| `ORCH_ALLOW_DIRECT_PROD_PUSH=1` | the integration rule above |
| `ORCH_ALLOW_UNVERIFIED_PROD_PUSH=1` | the green-build requirement |
| `ORCH_ALLOW_RED_TESTS=1` | the green-suite requirement |

A repo whose remote has no staging branch is not held to the rule. Set
`projects.staging_branch` for the one project that integrates somewhere else;
`ORCH_STAGING_BRANCH` changes the whole fleet at once, which is rarely what is
meant.

The guard only reaches a repo whose `core.hooksPath` points at
`runner/hooks`. After cloning:

    git config core.hooksPath /Users/kpasch/Documents/beethoven/claude-orchestrator/runner/hooks


## Database migrations: main only (owner decision 2026-10-03)

**The orchestrator only applies migrations that are already on main.** No session, agent,
loop or script applies a migration to a production database from a feature branch, a
worktree, or a staging branch.

    write the migration on your branch  ->  merge to consolidation/main (the project's staging branch)
        ->  promote to main  ->  THEN apply, from a clean checkout of origin/main

- Never use the Supabase MCP `apply_migration` against a production project (smarter
  `olaxnyrzoptjcntrrjgn`, apparently-law `cwmeqqtvmjbapjsefbfq`, or any ref in
  `runner/deployment_bindings.json`). It applies whatever SQL you hand it and records a
  fresh version that has no file on main, which is what broke `check:migration-ledger`
  and the production builds on 2026-10-03. The same goes for DDL through `execute_sql`,
  `supabase db push` from a feature checkout, and `supabase migration repair`.
- Never reuse a migration version. One version means one file on main and one ledger row.
- A destructive migration (DROP TABLE/SCHEMA/COLUMN, TRUNCATE, DELETE FROM) needs the
  owner's explicit OK for that version *as well as* being on main.

`runner/migration_main_guard.py` enforces this in `runner/apply_sql_migrations.py` and in
`runner/action_runner.py` (the "Run for me" / periodic path for `supabase db push`). It
refuses unless the file exists byte-identical on the target repo's production branch and
its version does not collide with the production ledger. It also ships a Claude Code
PreToolUse hook (`python3 runner/migration_main_guard.py claude-hook`) that refuses MCP
`apply_migration` and DDL `execute_sql` against production refs. See
`docs/database-steering.md` → "Applying migrations: main only".

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

Commits in this repo MUST be authored as one of these approved identities:

- kale@smrter.us
- mandyjustinepasch@gmail.com
- kale@heretomorrow.us
- kalepasch@gmail.com (repo owner, `kalepasch1` — the default)

Default to the repo owner:

    git config user.name "kalepasch1"
    git config user.email "kalepasch@gmail.com"

Run this immediately after cloning, before your first commit. Any of the
approved emails above is fine as the author (e.g. when a different Claude
account is committing as mandyjustinepasch@gmail.com). Do not use any other
identity, including your platform account identity.


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

## Never search the home directory for a repo

`projects.repo_path` holds the exact absolute path of every repo in the fleet. Ask
the control plane; it answers in milliseconds.

```sql
select name, repo_path from projects;
```

**Do not** run `find ~`, `bfs /Users/...`, `fd` or `mdfind` across the home
directory to locate a project, a file or a branch. Measured on this Mac,
2026-09-03:

| process | age | CPU |
|---|---|---|
| `bfs /Users/kpasch -type d -name sustainable-barks` | 11m58s | 82.6% |
| `bfs /Users/kpasch -type d -name *pareto*` | 4m42s | 68.1% |
| `bfs /Users/kpasch -type f -name *agentledger*` | live | 86.5% |

Three at once is roughly two and a half cores. It is not free, and it is not only
your task's problem:

- `resource_governor` clamps task lanes on load per core, and `merge_train`'s
  project workers now follow the same curve. At load/core 7.69 the fleet ran
  **one** merge worker instead of four and **one** task lane — so a home-directory
  scan throttles everybody's throughput, including the merge of your own work.
- A red suite produced on a box in that state is not a verdict about the code.
- When your session ends, an in-flight scan is reparented to launchd and keeps
  burning a core with nobody left to read its output. `resource_medic` now reaps
  those (`reaped-orphan-scan`), but not until they have already cost minutes.

Killing one of them took the 1-minute load average from 67 to 31.

If you genuinely need to search, bound it to the repo you are working in — the
worktree you were given, or a `repo_path` from the table. A search rooted at `.`
inside a project is fine and nothing here objects to it.


## Learned from merged work (auto)
Here are the extracted conventions and DO/AVOID rules:

**Conventions:**

* Use `pytest` fixtures to stub out expensive or slow functionality, such as the `env_permission_sweep` function.
* Use `autouse` fixtures to make them run automatically for all tests in a module.
* Use `allow_env_sweep` markers to opt-in to using the real `env_permission_sweep` function.
* Use `Convention-lint` to check for coding conventions and report any grandfathered violations.
* Document changes to production code in the commit message.

**DO/AVOID rules:**

* DO use profiling and instrumentation to measure and optimize performance-critical code.
* DO use `cProfile` to measure execution time and identify performance bottlenecks.
* DO use `Instrumented walk` to measure directory traversal and optimize performance.
* AVOID making changes to production code that are not explicitly documented in the commit message.
* AVOID making changes that break existing functionality without a clear justification.


## Learned from merged work (auto)
Here are the extracted **CONVENTIONS** and **DO/AVOID rules**:

**Conventions:**
* Use `pytest` fixtures to stub out expensive or slow functionality.
* Use `autouse` fixtures to make them run automatically for all tests in a module.
* Use `allow_env_sweep` markers to opt-in to using the real `env_permission_sweep` function.
* Use `Convention-lint` to check for coding conventions and report any grandfathered violations.
* Document changes to production code in the commit message.

**DO/AVOID rules:**
* DO use profiling and instrumentation to measure and optimize performance-critical code.
* DO use `cProfile` to measure execution time and identify performance bottlenecks.
* AVOID making changes to production code that are not explicitly documented in the commit message.
* AVOID making changes that break existing functionality without a clear justification.


## Consilium model policy (operator direction, 2026-09-29)

Use local super-intelligent models as much as possible. When cloud models (Fable, Opus, Sonnet,
GPT-5.5) are unavailable or stop working, always run lower-intelligence work instead of stopping,
so there is never a break in effort.

- Every model call goes through `runner/frontier.py::complete`, which walks
  Claude -> GPT-5.5 (Codex) -> the strongest local model and records the answering tier in
  `result["tier"]`. Routine no-tool work (need <= 6) goes to a resident 20B+ local model first.
- Jobs gate on `frontier.can_think(...)`, never on `frontier.available(...)` alone.
  `available()` means "Claude specifically", used only to prefer Claude when it is up.
- A lower tier keeps work moving but may not make judgements that need a stronger one: pass
  `min_tier="codex"` for scoring experts (theory_lab resolutions) and building playbooks. A
  local-tier commission review is provisional (cannot publish, cannot withdraw a card, redone when
  a cloud reviewer returns). A local-tier docket clerk may re-prioritise but not retire or rewrite.
- Label every artifact produced below the frontier tier with its tier.
- The firm (runner/escalation.py): associate (local, fast 35B) -> senior associate (local, next rung,
  e.g. 80B) -> counsel (largest local rung, e.g. 122B; else Sonnet; else GPT-5.5) -> partner (Fable;
  GPT-5.5 when Claude is down). Low and medium priority may finish at the associate or senior level when
  earned; high priority always reaches counsel. Counsel spot-checks a fixed 25% of lower-level finals, and
  each level's agreement rate sets its local-final threshold. Senior and counsel review packets and write
  from the evidence ledger; the partner opens the web only for gaps the associate could not fill locally.

