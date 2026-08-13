# Claude interface ↔ prompt-evolution bandit: current state and required changes

Scope: locate the Claude interface used by the prompt-evolution feature, describe its
current API and call patterns, check what the prior failed builds left behind, and name
the specific changes needed to let the bandit drive prompt-variant selection.

**Headline finding: nothing is missing from the bandit. It is finished, tested, and
imported by zero modules.** `grep -rn "prompt_evolution_bandit" runner/*.py`, excluding
its own file and its tests, returns nothing. The work left is wiring and one schema
column — not algorithm code. Two prior branches confirm this from opposite directions.

---

## 1. Current state

### 1.1 The Claude interface

`runner/claude_cli.py` is the single metered entry point.

```python
def run(prompt, model, cwd=None, env=None, project=None, max_turns=60,
        permission="acceptEdits", timeout=None, output_only=True):
    """Metered Claude call. Returns {text, cost_usd, input_tokens, output_tokens, returncode, raw}."""
```

Relevant properties:

* It takes a **fully-assembled prompt string**. It has no notion of a template, a
  variant, or an experiment — and it should not acquire one. Variant selection belongs
  upstream, at assembly.
* It is budget- and kill-switch-gated (`_check_budget`, `_paused`), and returns
  `returncode: 75` with `skipped: "kill_switch"` when paused. A skipped call is **not**
  evidence about a prompt variant; feeding it to the bandit as reward 0.0 would punish a
  variant for an unrelated outage.
* `cost_usd` / `input_tokens` / `output_tokens` come back on every call, so a
  cost-weighted reward (success-per-dollar, as `bandit._reward` already does for model
  routing) is available without any new plumbing.

### 1.2 Where prompts are assembled and outcomes recorded

Both touch points are already in `runner/runner.py`, both fail-soft, and they are the
natural bandit seams:

| Line | Call | Role |
|---|---|---|
| ~1266 | `prompt_evolution.get_evolved_additions(t, name)` → appended to `_extras` | **selection seam** — where a variant's text would be chosen |
| ~2537 | `prompt_evolution.record_prompt_outcome(t, draft_prompt, visible_model, integrated, _pe_cost, attempt)` | **reward seam** — `integrated` is the first-pass-merge signal the bandit wants |

The prompt actually sent is `draft_prompt` (runner.py ~1161–1176: base prompt, then
optional plan injection, adaptive probe, and `_cap_agent_prompt` truncation).

### 1.3 The existing evolution mechanism

`runner/prompt_evolution.py` correlates *structural features* of a prompt with first-pass
merges and evolves the template on a fixed schedule, at most two changes per cycle,
persisting to `prompt_evolution_log`. It is a one-armed hill climb: it can tell you which
features correlate, but it cannot run two candidate templates side by side and let
outcomes decide. That gap is exactly what the bandit was written for — its own module
docstring says so.

### 1.4 The bandit, as built

`runner/prompt_evolution_bandit.py` (280 lines) wraps `bandit.BanditSelector` and exposes
a module-level singleton per repo convention:

```python
select_action(arm_ids=None, rng=None) -> str    # "" when there is nothing to pick
update(arm_id, reward) -> float                 # 1.0 merged / 0.0 not, or any float
accept(arm_id) -> bool                          # promotion gate
stats() -> dict
reset() -> None
```

* `accept()` requires **two** gates: `min_pulls` (default 12, `ORCH_PROMPT_BANDIT_MIN_PULLS`)
  and a `margin` (default 0.05, `ORCH_PROMPT_BANDIT_MARGIN`) over the best *other* arm. A
  sole arm can never be accepted — no incumbent, no evidence.
* Every public method is fail-soft: it logs and degrades to the first arm / 0.0 / False.
  A broken bandit cannot wedge the runner.
* Arm mechanics are **not** reimplemented — validated construction, untried-arm-first
  selection, decayed epsilon and O(1) incremental means all come from `BanditSelector`.
* Tunables: `ORCH_PROMPT_BANDIT_EPSILON` (0.15), `ORCH_PROMPT_BANDIT_DECAY` (0.01).

### 1.5 The blocker, stated by the code itself

```python
# The real reward source is the `outcomes` table (see bandit._outcomes). Wiring
# that up means a schema column that records which prompt variant produced each
# outcome, which does not exist yet.
def load_performance(db=None, limit=2000):
    return {}
```

`load_performance` and `warm_start` are deliberate stubs with final signatures. **The
single hard dependency is `outcomes.prompt_variant`.** Without it a restart is a cold
start and no history can be replayed.

---

## 2. Prior branches and artifacts

Checked, since the task asks and since two of these change what is worth building.

| Branch | State | Verdict |
|---|---|---|
| `agent/…-prompt-evolution-bandit-wire-bandit-into-pipelin` | commit `5d28f0de`, **empty diff vs master**, no unique commits | The prior "failed build" produced nothing. Nothing to salvage, nothing to fear overwriting. |
| `agent/…-prompt-evolution-bandit-implement-performance-tr` | commit `7645d631`, **+605 lines, unmerged** — `PerformanceTracker` with confidence intervals + acceptance gate, 363 lines of tests | **Real, relevant, unmerged work. Reconcile before writing a new acceptance gate.** `grep -c PerformanceTracker runner/bandit.py` on master = 0. |
| `agent/…-prompt-evolution-bandit-add-bandit-algorithm-cor` | commit `6e627706` | Superseded — the algorithm is on master. |
| `agent/…-prompt-evolution-bandit-add-test-checks` | `recovery-intent-stub`, 4-line txt | Stub only. |

**Overlap that must be resolved first:** `PerformanceTracker` keeps raw reward samples so
it can answer *"is that difference real"* with a confidence interval, whereas the merged
`peb.accept()` uses a fixed `margin` over running means. These are two answers to one
question. Picking one — and deleting or explicitly subordinating the other — is a
prerequisite, not a follow-up; shipping both is how the four rival convention linters in
this repo happened.

---

## 3. Required modifications

Ordered so each step is independently mergeable and reversible.

### R1 — `outcomes.prompt_variant` column *(unblocks everything)*
Nullable TEXT on `outcomes`. Nullable is required: every historical row predates variants,
and a NOT NULL default would silently attribute all past outcomes to one arm.

### R2 — Record the variant at the reward seam
At runner.py ~2537, pass the selected variant into `record_prompt_outcome`, which writes it
to the new column. Signature gains a keyword-only `prompt_variant=None` so existing callers
are unaffected.

### R3 — Select at the assembly seam
At runner.py ~1266, call `peb.select_action(variant_ids)` and append that variant's
additions instead of the unconditional `get_evolved_additions`. Must stay inside the
existing `try/except` — a bandit failure returns `""` and the current behaviour resumes.

### R4 — Feed reward from the real outcome
`reward = 1.0 if integrated else 0.0` at the reward seam. **Skip the update entirely when
`returncode == 75` / `skipped == "kill_switch"`** — a paused project is not evidence against
a variant. Optionally weight by `cost_usd` for success-per-dollar.

### R5 — Implement `load_performance` / `warm_start`
Replace the stubs with a real read of `outcomes(prompt_variant, tests_passed, usd)`.
Signatures are already final, so no call site changes.

### R6 — Reconcile with `PerformanceTracker` (branch `7645d631`)
Decide: CI-based acceptance or margin-based. Merge the winner, close the loser with a
pointer to it. Do this **before** R3 lands, or the promotion rule changes underneath a
live experiment.

### R7 — Promotion path for `accept()`
Nothing consumes `accept()` today. Wire it to `prompt_evolution.evolve_template` so a
variant that clears both gates is promoted to the live template, and record the promotion
in `prompt_evolution_log` for auditability.

### R8 — Telemetry
Surface `peb.stats()` (counts, means, epsilon, min_pulls, margin) wherever fleet health is
reported. An unobservable bandit cannot be debugged when it converges on the wrong arm.

### Non-goals
* **Do not** teach `claude_cli.run` about variants. It takes an assembled string; keeping
  the experiment out of the metered call keeps budget accounting and A/B logic separable.
* **Do not** reimplement arm mechanics. `BanditSelector` owns them and is now covered by
  24 dedicated tests for `update` alone.

---

## 4. Checklist of files to change

| File | Change | Step |
|---|---|---|
| `supabase/migrations/<new>.sql` | add nullable `prompt_variant TEXT` to `outcomes` | R1 |
| `runner/prompt_evolution.py` | `record_prompt_outcome(..., prompt_variant=None)`; persist it | R2 |
| `runner/runner.py` (~2537) | pass the selected variant; call `peb.update(variant, reward)`; skip on kill-switch | R2, R4 |
| `runner/runner.py` (~1266) | `peb.select_action(...)` inside the existing fail-soft block | R3 |
| `runner/prompt_evolution_bandit.py` | implement `load_performance` / `warm_start` | R5 |
| `runner/bandit.py` | land or reject `PerformanceTracker` from `7645d631` | R6 |
| `runner/prompt_evolution.py` | consume `accept()` → promote variant to live template | R7 |
| `runner/tests/test_prompt_evolution_bandit.py` | cases for variant recording, kill-switch exclusion, warm start | R2, R4, R5 |
| fleet health surface | expose `peb.stats()` | R8 |

**Verification for each step:** `python3 -m pytest runner/tests/test_prompt_evolution_bandit.py
runner/tests/test_bandit_selector_update.py -q`, plus the offline guard suite
(`runner/tests/test_ci_offline.py`) which CI blocks on.
