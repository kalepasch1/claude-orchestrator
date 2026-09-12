# The queue cannot record "this cannot be done"

**Measured 2026-08-25, one cowork-executor session, five batches.**

Every `BLOCKED` verdict written during this session — eight of them, each with a
measured rationale naming exactly what was missing — was overwritten by the
agentic-repair daemon within minutes. The task went back to `QUEUED`, `attempt`
incremented, and `note` replaced with the literal string `agentic-repair:rework`.

This is not a slow leak. Two tasks were blocked, re-queued, re-claimed by the
same session, blocked again with a fresh measurement, and re-queued again inside
twenty minutes.

## The evidence

| slug | attempt when seen | state after blocking | note after |
|---|---|---|---|
| `…ap-6-live-reg-ap6a-portal-recon` | 1 → 2 → 3 → **4** | QUEUED | `agentic-repair:rework` |
| `…orchestrator-intake-backlog-darwin-kernel-rollout…galop-money-capabilities` | 5 → **6** | QUEUED | `agentic-repair:rework` |
| `…tomorrow-apparently-pareto-bridges-perpetu-slice-5` | 2 → **3** | QUEUED | `agentic-repair:rework` |
| `…pareto-life-goal-autonomy-stack-p7-crowd-benchmark-exchange` | 1 → **2** | QUEUED | `agentic-repair:rework` |
| `…pareto-life-goal-autonomy-stack-n3-audit-proof-life` | 1 → **2** | QUEUED | `agentic-repair:rework` |
| `…pareto-life-goal-autonomy-stack-p1-life-state-machine` | 0 → **1** | QUEUED | `agentic-repair:rework` |
| `…mission-complete-merge-and-deploy-the-full-slice-2` | 0 → **1** | QUEUED | `agentic-repair:rework` |
| `…pareto-life-goal-autonomy-stack-p6-earnings-only-interface` | **22** | QUARANTINED | `repair-ceiling` |

`DONE` and `SUPERSEDED` verdicts from the same session survived untouched. Only
`BLOCKED` is erased.

## Why it matters more than any single task

An executor that finds a task impossible has exactly one way to say so, and it
is being deleted. So the next executor re-derives the same finding from scratch,
at full cost, and is deleted too. `attempt=22` on the P6 task is twenty-two
independent agents reaching the same conclusion and having it thrown away.

The repair ceiling does eventually fire — P6 reached it at attempt 22 — but at
that point the queue has paid twenty-two times for one answer, and the
QUARANTINED note records `repair-ceiling`, not *why* the task was impossible.
The reason is still lost.

## The fix

`BLOCKED` with a rationale is a **terminal** state, not a transient failure.
The rework requeue should skip it, or the daemon should preserve the prior note
rather than overwriting it. A task that has been blocked with a measured
rationale twice should escalate to the operator, not go round again.

## The rationales that were erased

Recorded here because the queue would not keep them. Each was measured against
`origin`, not read from a prior note.

### 1. `apparently/proving/` does not exist (AP-6a portal recon)

The task requires the §5 proving harness AP-1..AP-5 to **exist** and explicitly
forbids rebuilding it. On `kalepasch1/apparently`:

```
git ls-tree -r origin/master --name-only | grep -c "proving/"            # 0
git ls-tree -r origin/orchestrator/dev --name-only | grep -c "proving/"  # 0
git ls-tree -r origin/master --name-only | grep -c "\.py$"               # 7
```

The repo is a Nuxt/TS app. A Python harness at that path has no host. A later
"sharpened" rewrite named `apparently/proving/ap1.py` specifically — also 0 hits.
The rewrite got more precise about a file that does not exist rather than
checking whether it does.

Secondary: the task drives **live** regulator portals (NMLS, FINRA, SEC/IARD,
CFTC/NFA, state boards) through real session/auth, CAPTCHA and MFA. Its own hard
limits — no submission, no fees, no real identity — cannot be enforced by an
unattended run.

**Unblock:** queue AP-1..AP-5 creation first, or repoint at the repo that holds
the harness.

### 2. The `pareto/2080` Python package does not exist (P1, P6, P7, N3)

Four tasks in the life-goal-autonomy-stack family instruct:

```python
from pareto.2080.contracts.autonomy import Receipt
```

This is a `SyntaxError` in any Python. A module path segment cannot begin with a
digit, so `2080` cannot follow a dot. No file layout makes it work, and every one
of these tasks has an acceptance test that imports it.

On `kalepasch1/2080`, `git ls-files "*.py"` returns exactly one path:
`scripts/delete-remote-branches.py`. There is no `contracts/` tree, no
`autonomy` module, no `life_sm/`, no `audit/`, no `earnings_ui/`. It is a
Nuxt/Vue app whose autonomy code is JavaScript — `server/utils/autonomyPolicy.js`,
`autonomyLab.js`, `autonomySimulate.js`, with suites in `tests/`.

The P6 prompt additionally ships as a **broken bash script**:
`mkdir -p .../{surface.py,decision_budget_lint.py,__init__.py}` creates
*directories* named like files, and the generated test body ends with a bare
comment inside a `with pytest.raises(SystFailure):` block — a `SyntaxError`
raising an undefined name.

**Unblock (retires all four at once):** decide where this Python lives, give it
an importable package name that is not `2080`, or re-scope the stack onto the
existing JavaScript modules with a JS acceptance command.

### 3. The darwin kernel is not in `racefeed` (galop money capabilities)

The task routes `cash_out` / `operator_payout` / `commingle_pool` through "the
kernel constitution", using "the kernel vendored by galop-passport-mint", and
says **do not re-edit the provider seam**. On `kalepasch1/racefeed` origin/master:

```
git ls-tree -r origin/master --name-only | grep -iE "kernel|constitution|passport"
# -> supabase/functions/compliance-passport/index.ts   (only match)
```

No vendored kernel, no constitution module. Implementing the routing means
writing the kernel the task forbids touching.

Three of the four named RPCs also do not exist — `operator_payout`,
`commingle_pool` and `reveal_winner_pre_lock` return 0 hits. Only `cash_out`
does, as `public.rf_cash_out`
(`supabase/migrations/20260619000001_game_rpcs.sql:199`, redefined at
`20260714010000_operator_readiness.sql:219`, called from `hooks/useCoins.ts:32`).

This is money-flow code. Inventing deny/escalate verdicts for RPCs that do not
exist, against a policy kernel that does not exist, ships a security control
that looks enforced and enforces nothing — the worst available outcome on a
cash-out path.

**Unblock:** land the kernel in `racefeed` (or name the repo that has it), define
or drop the three missing RPCs, and repoint the task row from `tomorrow` to
`/Users/kpasch/Documents/galop/racefeed`.

### 4. The prompt generator is emitting token dumps, not intent (bridges slice-5)

The `Intent:` line of this task reads:

> `07062319 07071626 30min 8b92d078e856 acceptance adapt agentic alter analysis
> artifacts because beethoven before behavior below blocks branch broad bugfix
> build category cause changes changing`

Alphabetical, `acceptance` → `changing`: a truncated A–C slice of a vocabulary
list, not a sentence. The rest is nested `MERGED-DIFF LIBRARY` / `PATCH
TRANSPLANT` / `PATCH TEMPLATE` headers quoting each other across three unrelated
repos, and the only acceptance criterion is "preserve existing behavior, make the
smallest mergeable diff", which names no behaviour and no file.

The sharpener then made it worse. Its "clearer" instruction was:

> Execute the "MERGED-DIFF LIBRARY" task on **SOURCE:
> pareto-2080/qafix-…-slice-1-slice-4** with a **similarity=0.515** score.

It has mistaken a diff-reuse index entry and its cosine score for a task to
perform. `0.515` is a similarity number.

**Unblock:** this is a generator bug, not a task bug. Every slice built from the
template is unactionable by construction; fixing the generator retires the whole
family.

### 5. `runner/.env` is not a committable scope

The entire request body is `Scope: runner/.env ONLY.` — no key, no value, no
behaviour. `runner/.env` is the per-machine credential file, gitignored by
design. Committing it, or any diff whose only scope is it, re-creates the
2026-08-02 plaintext-credential incident in git history where it cannot be
deleted.

**Unblock:** if a fleet-wide knob is wanted, name the key and route it through
`fleet_config` (it must pass `is_safe_config_key`). If a credential needs
setting, that is an operator action per host.

## Two smaller findings from the same session

**Mis-routing is systemic.** Six tasks carried a `project_id` pointing at a repo
that does not contain the code they name: pareto rebrand copy filed against
`tomorrow`, a `pytest` persona-registry acceptance filed against a Nuxt app, a
`fleet_config` contracts task filed against `tomorrow`, the galop task filed
against `tomorrow`. Each cost a full audit to discover.

**The retry classifier mislabels infrastructure errors.** One task carried
"ATTEMPT 1 FAILED — Error classified as: test_failure" whose error text was
`Failed to authenticate: OAuth session expired and could not be refreshed`, with
the instruction "fix ONLY the code that caused these specific test failures".
There was no failing test and no code to fix.
