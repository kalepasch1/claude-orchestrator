# MISSION: Operator Lane — let the human ship app changes WHILE the queue churns, with zero collisions and zero queue slowdown

You are working in `~/Documents/beethoven/claude-orchestrator`. ADDITIVE to PROMPT-backlog-blitz.md and PROMPT-meta-optimizer.md — check their commits first, extend existing modules (`merge_train.py`, `runner.py` claim path, `repo_lock.py`, `intake_watcher.py`, `learn_from_merges.py`), never fork parallel systems. Repo conventions apply: ORCH_ config keys, no secrets, fail-soft, 20+ tests per new module, `stats()`/`invalidate()` on stateful modules, fleet propagation via git + `fleet_control`.

## DESIGN PRINCIPLE

The operator becomes a first-class lane in the existing isolation + merge-train system — same worktree isolation agents get, same serialized integration — plus two new primitives: a conflict FORECAST (what will the queue touch?) and a path RESERVATION (queue defers around the operator, never collides). The queue never pauses for operator work.

## PART 1 — FILE CLAIMS MAP (conflict forecast)

1. `runner/file_claims.py`:
   - For every QUEUED and RUNNING task, predict touched paths: parse explicit paths/globs from the task prompt and contract; supplement with historical diffs of similar slugs from `outcomes` (same project + similar title fingerprint); running tasks additionally report actual dirty paths from their worktree (cheap `git -C <wt> status --porcelain` scan).
   - Persist to a `file_claims` table (task_id, project, path_glob, confidence, source, updated_at). Refresh on claim, on task insert, and every 5 min for running tasks. Fail-soft: prediction failure → empty claim set, never blocks anything.
   - CLI: `python3 runner/file_claims.py check <project> <path...>` → for each path: clear | contested (task slug, status, queue position, ETA from current velocity). `--project <p>` dumps the project's full heatmap.
2. Dashboard card (web/): per-project heatmap of contested paths with task slug + state, so the operator can see where NOT to edit at a glance.

## PART 2 — OPERATOR RESERVATIONS (queue routes around the human)

3. `operator_locks` table (id, project, path_glob, reserved_by, reason, created_at, ttl_minutes DEFAULT 240, released_at NULL). Add migration.
4. Enforcement, all fail-soft and deferral-based (NEVER fail a task because of a reservation):
   - Runner claim step: skip (leave QUEUED, note `deferred: operator lock <id>`) any task whose predicted claims intersect an active reservation. Re-eligible automatically when the lock releases/expires.
   - Merge train: hold (skip this cycle, loud log) any branch whose diff paths intersect an active reservation.
   - Cap: max `ORCH_OPERATOR_LOCKS_MAX` (default 5) active reservations, max TTL 24h — a forgotten lock must never starve the queue; expiry auto-releases and notifies.
5. Reverse protection: if the operator tries to reserve a path a RUNNING task is already touching, refuse with the task slug and ETA — offer to watch and notify on completion instead.

## PART 3 — OPERATOR WORKFLOW CLI (one command each way)

6. `operator.sh start <project> <slug> [paths...]`:
   - Runs `file_claims.py check` on the given paths; prints conflicts and refuses (override flag available) if contested by a RUNNING task.
   - Creates an isolated worktree + branch `operator/<slug>` off fresh origin/base (reuse `setup-worktrees.sh`), takes reservations on the paths, prints the worktree path to edit in.
7. `operator.sh ship <slug>`:
   - Commits (if dirty), pushes `operator/<slug>`, inserts a merge-train row flagged `lane=operator` (HIGH priority: integrates next cycle, ahead of agent branches — operator time is the scarcest resource), releases the reservations on successful merge.
   - Operator branches go through the SAME gates as agent branches (build, verify, tests) — priority is about ordering, not gate-skipping.
8. `operator.sh status` / `operator.sh release <lock-id|all>`: list active locks, worktrees, and pending operator merges; manual release.
9. Sync-back: on operator merge, `learn_from_merges.py` processes the diff like any agent merge (knowledge loop learns from human code too), and running tasks in that project get the existing rebase-onto-fresh-base treatment at integration time — no manual coordination needed.

## PART 4 — GUARDRAILS + HYGIENE

10. Protected surfaces: `operator.sh start` refuses `runner/`, `.runtime/`, `supabase/migrations/` and the primary repo checkouts (not worktrees) with an explanation — orchestrator self-changes go through the improve lane/intake; runtime state is the queue's own working surface.
11. Nudge to intake: if `start` is invoked without contested paths and the reason text doesn't indicate urgency, print a one-line reminder that non-urgent changes can be dropped to `intake/` instead (don't block — just nudge).
12. CLAUDE.md: add a short "Operator lane" section documenting the workflow and the two hard rules (never edit the runner's primary checkouts; never hold a reservation past need).
13. Tests (20+ across the modules): claim prediction (explicit paths, globs, no-signal tasks), reservation intersection (glob vs glob), deferral + auto-re-eligibility, TTL expiry, cap enforcement, reverse-protection refusal, merge-train hold/release, protected-surface refusal, fail-soft on DB unavailability (reservations unreadable → queue proceeds normally, log loudly).

## ACCEPTANCE

- With the queue actively running: `operator.sh start web fix-nav web/components/Nav.vue` → worktree created, lock taken; a queued task predicted to touch `Nav.vue` shows `deferred: operator lock`; unrelated tasks keep claiming at full rate (verify running-lane count unchanged).
- `operator.sh ship fix-nav` → merged ahead of agent branches within one train cycle, gates enforced, lock released, deferred task becomes eligible and later integrates cleanly on rebased base.
- `file_claims.py check` returns a correct contested verdict for a path named in a queued task's prompt.
- Forgotten lock expires at TTL with notification; queue self-heals.
- `REPORT-operator-lane.md` documenting the workflow with a real end-to-end example.
