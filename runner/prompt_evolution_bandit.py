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
# Performance-data stubs.
#
# The real reward source is the `outcomes` table (see bandit._outcomes). Wiring
# that up means a schema column that records which prompt variant produced each
# outcome, which does not exist yet. Until it does, these return empty/neutral
# values so a caller can integrate against the final signature today and get
# real numbers the moment the column lands, rather than having to change call
# sites later.
# ---------------------------------------------------------------------------
def load_performance(db=None, limit=2000):
    """Historical per-variant rewards from the outcomes table.

    Returns {arm_id: [reward, ...]}. Empty until `outcomes.prompt_variant` exists.
    """
    return {}


def warm_start(db=None, arm_ids=None):
    """Seed the singleton from `load_performance` so a restart is not a cold start.

    Returns the number of rewards folded in (0 while the data source is a stub).
    """
    folded = 0
    try:
        for arm_id, rewards in (load_performance(db) or {}).items():
            for r in rewards:
                update(arm_id, r)
                folded += 1
    except Exception as e:
        _log.warning("warm_start failed (%s); starting cold", e)
    return folded
