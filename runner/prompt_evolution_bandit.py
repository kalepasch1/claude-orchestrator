#!/usr/bin/env python3
"""
prompt_evolution_bandit.py - epsilon-greedy arm selection for prompt-template
variants.

`prompt_evolution.py` already knows *which structural features* correlate with a
first-pass merge, but it evolves the template on a fixed schedule (at most two
changes per cycle) and has no way to run two candidate templates side by side and
let outcomes decide. This module is that missing piece: a small bandit whose arms
are prompt-variant ids.

The arm mechanics are NOT reimplemented here. `bandit.BanditSelector` already owns
validated construction, untried-arm-first selection, decayed epsilon, and O(1)
incremental means; this module wraps it in the select_action/update/accept
interface the prompt-evolution caller expects, and adds the one thing a *prompt*
bandit needs that a model-routing bandit does not: an acceptance gate, so a
variant is only promoted once it has both enough pulls and a real margin over the
incumbent.

Usage:
    import prompt_evolution_bandit as peb
    variant = peb.select_action(["baseline", "with_examples"])
    peb.update(variant, reward=1.0)          # 1.0 merged, 0.0 not
    if peb.accept(variant):
        ...  # promote this variant to the live template

Env vars:
    ORCH_PROMPT_BANDIT_EPSILON     initial exploration rate (default 0.15)
    ORCH_PROMPT_BANDIT_DECAY       per-step epsilon decay  (default 0.01)
    ORCH_PROMPT_BANDIT_MIN_PULLS   pulls required before accept() can pass (default 12)
    ORCH_PROMPT_BANDIT_MARGIN      reward margin over the incumbent for accept() (default 0.05)

Fail-soft: every public function swallows and logs its errors. A broken bandit
must degrade to "always the first arm", never wedge the runner that called it.
"""
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bandit import BanditSelector  # noqa: E402  (path shim must run first)

try:
    import log as _log_mod
    _log = _log_mod.get("prompt_evolution_bandit")
except Exception:  # pragma: no cover - logging must never be the failure
    class _Null:
        def info(self, *a, **k):
            pass

        warn = warning = error = debug = info
    _log = _Null()


def _env_float(name, default):
    """Read a float env var. Fail-soft: a malformed value falls back to default."""
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return float(default)


def _env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return int(default)


EPSILON = _env_float("ORCH_PROMPT_BANDIT_EPSILON", 0.15)
DECAY = _env_float("ORCH_PROMPT_BANDIT_DECAY", 0.01)
MIN_PULLS = _env_int("ORCH_PROMPT_BANDIT_MIN_PULLS", 12)
MARGIN = _env_float("ORCH_PROMPT_BANDIT_MARGIN", 0.05)


class Bandit:
    """Epsilon-greedy bandit over prompt-variant ids.

    Arms may be supplied up front or registered lazily on first sight, because the
    set of live prompt variants changes as `prompt_evolution.evolve_template`
    produces new ones — refusing an unseen variant would mean the newest template
    is the one that never gets measured.
    """

    def __init__(self, arm_ids=None, epsilon=None, decay=None,
                 min_pulls=None, margin=None):
        self._lock = threading.Lock()
        self.epsilon = EPSILON if epsilon is None else float(epsilon)
        self.decay = DECAY if decay is None else float(decay)
        self.min_pulls = MIN_PULLS if min_pulls is None else int(min_pulls)
        self.margin = MARGIN if margin is None else float(margin)
        self._selector = None
        if arm_ids:
            self._selector = BanditSelector(arm_ids, epsilon=self.epsilon,
                                            decay=self.decay)

    # ---------------------------------------------------------------- arms

    @property
    def arm_ids(self):
        return tuple(self._selector.arm_ids) if self._selector else ()

    def _ensure(self, arm_ids):
        """Grow the underlying selector to cover `arm_ids`, preserving learned stats.

        BanditSelector's arm set is fixed at construction, so adding a variant means
        building a new selector and carrying the old counts/means across. Rebuilding
        is cheap (arm counts are in the tens) and keeping the stats is what makes a
        newly-added variant comparable to the incumbent instead of resetting the
        whole experiment every time a template evolves.
        """
        wanted = []
        for a in (arm_ids or ()):
            if isinstance(a, str) and a and a not in wanted:
                wanted.append(a)
        if not wanted:
            return self._selector

        if self._selector is None:
            self._selector = BanditSelector(wanted, epsilon=self.epsilon,
                                            decay=self.decay)
            return self._selector

        missing = [a for a in wanted if a not in self._selector.counts]
        if not missing:
            return self._selector

        old = self._selector
        merged = list(old.arm_ids) + missing
        fresh = BanditSelector(merged, epsilon=self.epsilon, decay=self.decay)
        fresh.counts.update(old.counts)
        fresh.average_reward.update(old.average_reward)
        fresh.steps = old.steps
        self._selector = fresh
        return self._selector

    # ---------------------------------------------------------------- policy

    def select_action(self, arm_ids=None, rng=None):
        """Return the variant id to use next, or "" if there is nothing to pick.

        Untried variants are taken first (inherited from BanditSelector), then the
        epsilon-greedy explore/exploit split.
        """
        try:
            with self._lock:
                sel = self._ensure(arm_ids) if arm_ids else self._selector
                if sel is None:
                    return ""
                return sel.select(rng=rng)
        except Exception as e:
            _log.warning("select_action failed (%s); fail-soft to first arm", e)
            try:
                return self.arm_ids[0] if self.arm_ids else ""
            except Exception:
                return ""

    def update(self, arm_id, reward):
        """Record an outcome for `arm_id`. Returns the arm's new mean reward.

        `reward` is conventionally 1.0 for a first-pass merge and 0.0 otherwise, but
        any float works — callers that weight by cost can pass success-per-dollar the
        way `bandit._reward` does.
        """
        try:
            with self._lock:
                sel = self._ensure([arm_id])
                if sel is None:
                    return 0.0
                return sel.update_reward(arm_id, reward)
        except Exception as e:
            _log.warning("update(%r) failed (%s); fail-soft", arm_id, e)
            return 0.0

    def accept(self, arm_id):
        """True when `arm_id` has earned promotion to the live template.

        Two gates, both required. Enough pulls, so a variant cannot win on a single
        lucky merge; and a real margin over the best *other* arm, so a variant that
        merely ties the incumbent does not trigger a template churn that costs a
        cache invalidation and buys nothing. A sole arm can never be accepted —
        there is no incumbent to beat, so there is no evidence.
        """
        try:
            with self._lock:
                sel = self._selector
                if sel is None or arm_id not in sel.counts:
                    return False
                if sel.counts[arm_id] < self.min_pulls:
                    return False
                others = [a for a in sel.arm_ids if a != arm_id and sel.counts[a] > 0]
                if not others:
                    return False
                incumbent = max(sel.average_reward[a] for a in others)
                return sel.average_reward[arm_id] >= incumbent + self.margin
        except Exception as e:
            _log.warning("accept(%r) failed (%s); fail-soft to False", arm_id, e)
            return False

    def stats(self):
        """Telemetry snapshot. Empty dict when no arms have been registered."""
        try:
            with self._lock:
                if self._selector is None:
                    return {"steps": 0, "counts": {}, "average_reward": {},
                            "best_arm": "", "epsilon": self.epsilon}
                s = self._selector.stats()
                s["min_pulls"] = self.min_pulls
                s["margin"] = self.margin
                return s
        except Exception as e:
            _log.warning("stats failed (%s); fail-soft to empty", e)
            return {}

    def reset(self):
        """Drop all learned state. Used by tests and by a deliberate re-experiment."""
        with self._lock:
            self._selector = None


# ---------------------------------------------------------------------------
# Module-level singleton (repo convention: callers use the module functions and
# never have to thread an instance through the call chain).
# ---------------------------------------------------------------------------
_bandit = Bandit()


def select_action(arm_ids=None, rng=None):
    return _bandit.select_action(arm_ids, rng=rng)


def update(arm_id, reward):
    return _bandit.update(arm_id, reward)


def accept(arm_id):
    return _bandit.accept(arm_id)


def stats():
    return _bandit.stats()


def reset():
    return _bandit.reset()


# ---------------------------------------------------------------------------
# Performance data — real, sourced from `outcomes`.
#
# This block used to be a pair of stubs whose comment read "wiring that up means
# a schema column that records which prompt variant produced each outcome, which
# does not exist yet". That premise is stale: `outcomes` carries `experiment_id`
# and `experiment_variant` (written by runner.py:2601 via experiment_router), and
# those two columns are exactly the missing link. So `load_performance` now reads
# them, and every restart of the runner no longer throws away the fleet's entire
# prompt-variant history and re-explores from zero.
# ---------------------------------------------------------------------------

#: Only outcomes whose experiment_id starts with this belong to a *prompt*
#: experiment. Without the filter, model-routing and scheduler experiments would
#: be folded in as if they were prompt variants, and "control"/"candidate" from an
#: unrelated experiment would poison the arm statistics.
EXPERIMENT_PREFIX = os.environ.get("ORCH_PROMPT_BANDIT_EXPERIMENT_PREFIX", "prompt")

#: PostgREST caps one response at 1000 rows regardless of `limit`, so asking for
#: more only hides the truncation. This read is a SAMPLE in the taxonomy in
#: db.select_all's docstring: a bounded *recent* window is the right semantics here
#: (prompt templates evolve, so year-old rewards are not evidence about today's
#: arms) and the deterministic order makes the window reproducible.
_MAX_ROWS = 1000


def _outcome_reward(row):
    """Reward for one outcome row, in [0, 1].

    Deliberately NOT bandit._reward: that one is success-per-dollar and is
    unbounded above (it divides by cost + 0.01, so a free win scores 100). The
    prompt bandit's accept() gate compares means against MARGIN, which defaults to
    0.05 and is calibrated as a *rate* difference. Feeding it per-dollar rewards
    would make the margin meaningless. Prompt quality is also the thing being
    measured here — cost is the model's property, not the template's.

    1.0 merged first try, 0.2 tests passed but not integrated, 0.0 otherwise —
    the same tiering bandit._reward uses before its cost division.
    """
    if row.get("integrated") and row.get("tests_passed"):
        return 1.0
    if row.get("tests_passed"):
        return 0.2
    return 0.0


def load_performance(db=None, limit=_MAX_ROWS, experiment_prefix=None):
    """Historical per-variant rewards from the `outcomes` table.

    Returns {arm_id: [reward, ...]}, newest first, restricted to terminal rows of
    prompt experiments. Fail-soft: any DB problem yields {} and a warning, because
    a cold start is a slower bandit, not a broken runner.
    """
    prefix = EXPERIMENT_PREFIX if experiment_prefix is None else experiment_prefix
    conn = db
    if conn is None:
        try:
            import db as _db_mod
            conn = _db_mod
        except Exception as e:
            _log.warning("load_performance: no db module (%s); cold start", e)
            return {}

    try:
        cap = max(1, min(int(limit or _MAX_ROWS), _MAX_ROWS))
    except (TypeError, ValueError):
        cap = _MAX_ROWS

    params = {
        "select": "experiment_id,experiment_variant,tests_passed,integrated,created_at,id",
        "experiment_variant": "not.is.null",
        "order": "created_at.desc,id.desc",
        "limit": str(cap),
    }
    if prefix:
        params["experiment_id"] = f"like.{prefix}%"

    try:
        rows = conn.select("outcomes", params) or []
    except Exception as e:
        _log.warning("load_performance query failed (%s); cold start", e)
        return {}

    out = {}
    for r in rows:
        try:
            arm = r.get("experiment_variant")
            if not isinstance(arm, str) or not arm:
                continue
            out.setdefault(arm, []).append(_outcome_reward(r))
        except Exception:
            continue
    _log.info("load_performance: %d rewards across %d variants", 
              sum(len(v) for v in out.values()), len(out))
    return out


def warm_start(db=None, arm_ids=None, experiment_prefix=None):
    """Seed the singleton from `load_performance` so a restart is not a cold start.

    `arm_ids`, when given, restricts the fold-in to variants that are still live —
    a template that no longer exists should not keep influencing selection, and it
    must not be resurrected as an arm just because it has history.

    Returns the number of rewards folded in.
    """
    folded = 0
    try:
        wanted = set(arm_ids) if arm_ids else None
        perf = load_performance(db, experiment_prefix=experiment_prefix) or {}
        for arm_id, rewards in perf.items():
            if wanted is not None and arm_id not in wanted:
                continue
            for r in rewards:
                update(arm_id, r)
                folded += 1
    except Exception as e:
        _log.warning("warm_start failed (%s); starting cold", e)
    return folded


def analyze(arm_ids=None):
    """Explain the bandit's current state and why accept() does or does not pass.

    stats() reports the raw counters; this reports the *decision*. When a variant
    has been running for days and has not been promoted, the operator needs to know
    which of the two accept() gates is holding it — not enough pulls, or not enough
    margin — because those have opposite remedies (wait vs. abandon the variant).

    Returns a dict:
        arms       {arm_id: {"pulls", "mean"}} sorted by mean, best first
        leader     arm with the highest mean, or "" when there is no data
        runner_up  second-highest arm, or ""
        margin     leader.mean - runner_up.mean
        accepted   True when accept(leader) passes
        blocked_by "" | "insufficient-pulls" | "insufficient-margin" | "no-incumbent" | "no-data"
        min_pulls / required_margin  the thresholds in force
    """
    base = {"arms": {}, "leader": "", "runner_up": "", "margin": 0.0,
            "accepted": False, "blocked_by": "no-data",
            "min_pulls": _bandit.min_pulls, "required_margin": _bandit.margin}
    try:
        s = stats() or {}
        counts = s.get("counts") or {}
        means = s.get("average_reward") or {}
        if arm_ids:
            keep = set(arm_ids)
            counts = {k: v for k, v in counts.items() if k in keep}
            means = {k: v for k, v in means.items() if k in keep}

        pulled = [a for a, n in counts.items() if n > 0]
        base["arms"] = {
            a: {"pulls": counts.get(a, 0), "mean": round(float(means.get(a, 0.0)), 4)}
            for a in sorted(counts, key=lambda x: (-float(means.get(x, 0.0)), x))
        }
        if not pulled:
            return base

        ranked = sorted(pulled, key=lambda a: (-float(means.get(a, 0.0)), a))
        leader = ranked[0]
        base["leader"] = leader

        if len(ranked) < 2:
            base["blocked_by"] = "no-incumbent"
            return base

        runner_up = ranked[1]
        base["runner_up"] = runner_up
        base["margin"] = round(float(means.get(leader, 0.0)) - float(means.get(runner_up, 0.0)), 4)

        if counts.get(leader, 0) < _bandit.min_pulls:
            base["blocked_by"] = "insufficient-pulls"
        elif base["margin"] < _bandit.margin:
            base["blocked_by"] = "insufficient-margin"
        else:
            base["blocked_by"] = ""
            base["accepted"] = accept(leader)
        return base
    except Exception as e:
        _log.warning("analyze failed (%s); fail-soft", e)
        return base
