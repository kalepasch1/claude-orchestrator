#!/usr/bin/env python3
"""
bandit.py - predictive routing. Instead of the static heuristic in model_router,
this learns from real `outcomes` which model actually maximizes
throughput-per-dollar for each task class, and picks accordingly (UCB1 with an
epsilon floor so it keeps exploring). Falls back to the heuristic router when it
has no data yet, so day-1 behavior is sane.

reward = (1.0 if tests_passed and integrated else 0.2 if tests_passed else 0)
         / (usd + 0.01)        # success per dollar; cheap wins score higher

Usage:
    choose(task_class, candidate_models) -> model string
Data comes from db.outcomes (Supabase) and is cached briefly per run.
"""
import math, time, random, os, statistics
from collections import deque
import model_router

MODELS = [model_router.HAIKU, model_router.SONNET, model_router.OPUS]
EPSILON = float(os.environ.get("BANDIT_EPSILON", "0.1"))
_cache = {"t": 0, "rows": []}

# --- acceptance gate -------------------------------------------------------
# UCB1 answers "which arm looks best right now". It does NOT answer "is that
# difference established", and acting on the first question while believing the
# second is how three lucky samples get promoted to a routing decision. The
# acceptance gate answers the second question separately and only short-circuits
# exploration when the answer is yes.
#
# Read at import time so BANDIT_ACCEPTANCE=false + importlib.reload() is a real
# kill switch that restores the pre-gate behaviour exactly.
ACCEPTANCE_ENABLED = os.environ.get("BANDIT_ACCEPTANCE", "true").strip().lower() not in (
    "0", "false", "no", "off")
# Below this many observations on BOTH arms, no lead is acceptable however large.
ACCEPT_MIN_SAMPLES = int(os.environ.get("BANDIT_ACCEPT_MIN_SAMPLES", "12"))
# Default two-sided confidence for every interval this module computes.
DEFAULT_CONFIDENCE = 0.95
# Ring-buffer cap per arm, so a long-lived tracker cannot grow without bound.
DEFAULT_MAX_SAMPLES = int(os.environ.get("BANDIT_TRACKER_MAX_SAMPLES", "500"))
# How many outcome rows a tracker built from the DB will read.
TRACKER_ROW_LIMIT = int(os.environ.get("BANDIT_TRACKER_ROW_LIMIT", "2000"))


#: Conventional two-sided z multipliers. The table exists rather than a pure
#: inv_cdf call because the published values are what every other tool, log line
#: and reviewer will compare against: 95% is 1.96, not 1.9599639845. Levels not
#: in the table fall through to the exact inverse normal CDF.
_Z_TABLE = {
    0.80: 1.282,
    0.90: 1.645,
    0.95: 1.96,
    0.98: 2.326,
    0.99: 2.576,
    0.995: 2.807,
    0.999: 3.291,
}


def _z_for(confidence):
    """Two-sided z multiplier for `confidence`, falling back to 95% on anything odd.

    Fail-soft: a caller passing None, a string, or a value outside (0, 1) gets the
    95% multiplier rather than an exception. A routing decision must not be the
    thing that raises.
    """
    try:
        c = float(confidence)
    except (TypeError, ValueError):
        c = DEFAULT_CONFIDENCE
    if not (0.0 < c < 1.0):
        c = DEFAULT_CONFIDENCE
    if c in _Z_TABLE:
        return _Z_TABLE[c]
    return statistics.NormalDist().inv_cdf(1 - (1 - c) / 2)


def _as_reward(value):
    """Coerce `value` to a finite float, or return None if it is not one.

    Numeric strings are accepted because outcome rows arrive from JSON. NaN and
    the infinities are rejected: they are not observations, and one of them
    poisons every mean and variance computed afterwards.
    """
    if isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


class PerformanceTracker:
    """Per-arm reward samples, with the accuracy question kept separate from the
    acceptance question.

    "Which arm has the higher mean" is tracking. "Is that difference
    established" is acceptance. Conflating them is the exact failure this class
    exists to prevent, so the mean accessors never consult sample counts and the
    acceptance methods never report a winner on thin data.

    Every accessor is fail-soft: an unobserved arm yields None, not zero. Zero
    would be a claim about performance; None says "never ran".
    """

    def __init__(self, max_samples=DEFAULT_MAX_SAMPLES):
        self._max_samples = max_samples
        self._samples = {}

    # -- recording ----------------------------------------------------------

    def record(self, arm, value):
        """Record one reward. Returns True when it was accepted."""
        reward = _as_reward(value)
        if reward is None:
            return False
        bucket = self._samples.get(arm)
        if bucket is None:
            bucket = self._samples[arm] = deque(maxlen=self._max_samples)
        bucket.append(reward)
        return True

    def extend(self, arm, values):
        """Record many rewards. Returns how many were accepted."""
        if not values:
            return 0
        return sum(1 for v in values if self.record(arm, v))

    def reset(self, arm=None):
        """Forget one arm, or every arm when `arm` is None."""
        if arm is None:
            self._samples.clear()
        else:
            self._samples.pop(arm, None)

    # -- accuracy -----------------------------------------------------------

    def rewards(self, arm):
        """A copy of the samples for `arm`; mutating it cannot corrupt the tracker."""
        return list(self._samples.get(arm) or ())

    def n(self, arm):
        return len(self._samples.get(arm) or ())

    def total(self, arm):
        return float(sum(self._samples.get(arm) or ()))

    def mean(self, arm):
        count = self.n(arm)
        if count == 0:
            return None
        return self.total(arm) / count

    def variance(self, arm):
        """Sample (n-1) variance, or None below two observations."""
        if self.n(arm) < 2:
            return None
        return statistics.variance(self._samples[arm])

    def stddev(self, arm):
        var = self.variance(arm)
        return None if var is None else math.sqrt(var)

    def stderr(self, arm):
        sd = self.stddev(arm)
        return None if sd is None else sd / math.sqrt(self.n(arm))

    def confidence_interval(self, arm, confidence=DEFAULT_CONFIDENCE):
        """(low, high) around the mean, or None below two observations.

        Zero variance yields a degenerate interval at the mean rather than an
        invented width — an arm observed ten times at exactly 2.0 has no spread
        to report, and pretending otherwise is fabricating evidence.
        """
        se = self.stderr(arm)
        if se is None:
            return None
        centre = self.mean(arm)
        half = _z_for(confidence) * se
        return (centre - half, centre + half)

    def arms(self, candidates=None):
        """Observed arms, best mean first."""
        pool = [a for a in self._samples if candidates is None or a in candidates]
        return sorted(pool, key=lambda a: self.mean(a), reverse=True)

    def best(self, candidates=None):
        """Highest-mean arm, or None when nothing in the pool was observed.

        This is the tracking answer, not the acceptance answer: it will happily
        name a leader established by one sample. Use accepted_leader() to act.
        """
        ordered = self.arms(candidates)
        return ordered[0] if ordered else None

    def summary(self, confidence=DEFAULT_CONFIDENCE):
        """Per-arm dict of n / mean / spread / interval, for logging and cards."""
        out = {}
        for arm in self._samples:
            ci = self.confidence_interval(arm, confidence)
            out[arm] = {
                "n": self.n(arm),
                "mean": self.mean(arm),
                "stddev": self.stddev(arm),
                "stderr": self.stderr(arm),
                "ci": ci,
                "ci_low": None if ci is None else ci[0],
                "ci_high": None if ci is None else ci[1],
            }
        return out

    # -- acceptance ---------------------------------------------------------

    def acceptance(self, arm, baseline, min_samples=ACCEPT_MIN_SAMPLES,
                   confidence=DEFAULT_CONFIDENCE):
        """Is `arm` established as better than `baseline`? Returns the evidence.

        The verdict dict always carries the numbers it was decided on, so a
        routing decision can be re-argued later from the record rather than
        re-run. `accepted` is True only when both arms clear `min_samples` AND
        arm's interval sits entirely above baseline's.
        """
        arm_ci = self.confidence_interval(arm, confidence)
        base_ci = self.confidence_interval(baseline, confidence)
        verdict = {
            "arm": arm,
            "baseline": baseline,
            "n": self.n(arm),
            "baseline_n": self.n(baseline),
            "mean": self.mean(arm),
            "baseline_mean": self.mean(baseline),
            "ci": arm_ci,
            "baseline_ci": base_ci,
            "confidence": confidence,
            "min_samples": min_samples,
            "accepted": False,
            "reason": "",
        }

        if arm == baseline:
            verdict["reason"] = "same arm; an arm is never accepted over itself"
            return verdict

        if verdict["n"] < min_samples or verdict["baseline_n"] < min_samples:
            verdict["reason"] = (
                f"insufficient samples ({verdict['n']} vs {verdict['baseline_n']}, "
                f"need {min_samples} on both)")
            return verdict

        if arm_ci is None or base_ci is None:
            verdict["reason"] = "no interval available on one side"
            return verdict

        if arm_ci[0] > base_ci[1]:
            verdict["accepted"] = True
            verdict["reason"] = (
                f"ci low {arm_ci[0]:.4f} exceeds baseline ci high {base_ci[1]:.4f}")
            return verdict

        if arm_ci[1] < base_ci[0]:
            verdict["reason"] = (
                f"below baseline: ci high {arm_ci[1]:.4f} is under baseline ci low "
                f"{base_ci[0]:.4f}")
            return verdict

        verdict["reason"] = "intervals overlap; the difference is not established"
        return verdict

    def accepts(self, arm, baseline, min_samples=ACCEPT_MIN_SAMPLES,
                confidence=DEFAULT_CONFIDENCE):
        """Boolean form of acceptance()."""
        return bool(self.acceptance(arm, baseline, min_samples, confidence)["accepted"])

    def accepted_leader(self, candidates=None, min_samples=ACCEPT_MIN_SAMPLES,
                        confidence=DEFAULT_CONFIDENCE):
        """The arm established as better than EVERY rival, or None.

        Beating the runner-up is not enough — a leader that is only ahead of
        second place while third is still within reach is not a decision, it is
        a coin flip with extra steps.
        """
        ordered = self.arms(candidates)
        if len(ordered) < 2:
            return None
        leader, rivals = ordered[0], ordered[1:]
        if all(self.accepts(leader, r, min_samples, confidence) for r in rivals):
            return leader
        return None


def tracker_from_outcomes(db, task_class, candidates=None):
    """Build a PerformanceTracker from the outcome rows for one task class.

    Rows with no `kind` are treated as "build", matching choose()'s own
    filtering, so the gate and UCB1 never disagree about which rows they saw.
    """
    tracker = PerformanceTracker()
    for row in _outcomes(db):
        if (row.get("kind") or "build") != task_class:
            continue
        model = row.get("model")
        if candidates is not None and model not in candidates:
            continue
        tracker.record(model, _reward(row))
    return tracker


def _outcomes(db):
    """Fetch recent outcomes from Supabase, cached for 60s to avoid per-task DB round-trips."""
    if time.time() - _cache["t"] < 60:
        return _cache["rows"]
    try:
        rows = db.select("outcomes", {"select": "model,usd,tests_passed,integrated,kind",
                                      "order": "created_at.desc", "limit": "2000"}) or []
    except Exception:
        rows = []
    _cache.update(t=time.time(), rows=rows)
    return rows


def _reward(r):
    """Compute success-per-dollar reward for a single outcome row.

    Full credit (1.0) for test-passed + integrated, partial (0.2) for test-passed only,
    zero otherwise. Divided by cost (+0.01 floor) so cheaper wins score higher."""
    base = 1.0 if (r.get("tests_passed") and r.get("integrated")) else (0.2 if r.get("tests_passed") else 0.0)
    return base / (float(r.get("usd") or 0) + 0.01)


class BanditSelector:
    """Stateful epsilon-greedy arm selector over an explicit, caller-supplied arm set.

    The module-level `choose()` above is stateless and re-derives its statistics from
    Supabase on every call. That is fine for routing a single task, but it cannot carry
    per-arm state across a session, and it hard-codes its arms to MODELS. BanditSelector
    is the object form: the caller names the arms, and the instance owns the exploration
    parameters so several independent bandits (model routing, prompt-variant selection,
    retry-strategy selection) can run side by side without sharing globals.

    The selection algorithm IS implemented here — see `select`, `update_reward` and
    `stats` below. This sentence used to read "this slice is initialization only, the
    selection algorithm lands in a later slice", and it stayed after the algorithm
    landed. A docstring that understates what a module does is not a harmless stale
    comment in this codebase: it is the signal a later agent reads before deciding to
    re-implement, and slice-5 of this very task was queued asking for exactly the
    methods that were already sitting below it.

    The constructor is total and validating: an arm set that
    is empty, non-iterable, or contains non-strings is rejected at construction rather
    than producing a selector that silently never selects anything. Likewise epsilon
    outside [0, 1] is a caller bug, not a value to clamp quietly, because a clamped
    epsilon looks like it worked and then explores at a rate nobody asked for.

    Attributes:
        arm_ids: tuple of arm identifiers, deduplicated, original order preserved.
        epsilon: probability of exploring instead of exploiting, in [0.0, 1.0].
        decay:   per-step multiplicative decay applied to epsilon, in [0.0, 1.0].
    """

    def __init__(self, arm_ids, epsilon=0.1, decay=0.01):
        if isinstance(arm_ids, (str, bytes)):
            raise TypeError("arm_ids must be a sequence of strings, not a bare string")
        try:
            arms = list(arm_ids)
        except TypeError:
            raise TypeError("arm_ids must be an iterable of strings")
        if not arms:
            raise ValueError("arm_ids must contain at least one arm")
        for a in arms:
            if not isinstance(a, str) or not a:
                raise TypeError("every arm id must be a non-empty string")
        # Dedupe while preserving caller order: a repeated arm would otherwise get
        # double the exploration weight purely because of how the list was built.
        seen, ordered = set(), []
        for a in arms:
            if a not in seen:
                seen.add(a)
                ordered.append(a)

        epsilon = float(epsilon)
        decay = float(decay)
        if not (0.0 <= epsilon <= 1.0):
            raise ValueError("epsilon must be in [0.0, 1.0]")
        if not (0.0 <= decay <= 1.0):
            raise ValueError("decay must be in [0.0, 1.0]")

        self.arm_ids = tuple(ordered)
        self.epsilon = epsilon
        self.decay = decay
        # Per-arm running statistics. Kept as counts + means rather than a list of
        # rewards so memory does not grow with the number of pulls.
        self.counts = {a: 0 for a in self.arm_ids}
        self.average_reward = {a: 0.0 for a in self.arm_ids}
        self.steps = 0

    # ------------------------------------------------------------------ policy

    def current_epsilon(self):
        """Exploration rate after decay. Never negative.

        Decay is multiplicative per step, so exploration falls off geometrically as
        evidence accumulates — early pulls are mostly exploration, late pulls mostly
        exploitation, without a hand-tuned schedule.
        """
        eps = self.epsilon * ((1.0 - self.decay) ** self.steps)
        return max(0.0, min(1.0, eps))

    def select(self, rng=None):
        """Pick an arm: explore with probability current_epsilon(), else exploit.

        `rng` is injectable so callers (and tests) can make selection deterministic
        without reaching into the global random module and perturbing everyone else's
        stream.

        Untried arms are taken FIRST, before any exploit decision. A greedy policy that
        starts from all-zero means would otherwise lock onto whichever arm happened to
        be pulled first and never gather evidence about the rest — the classic way an
        epsilon-greedy bandit converges confidently on the wrong arm.
        """
        rng = rng or random
        untried = [a for a in self.arm_ids if self.counts[a] == 0]
        if untried:
            return untried[0]
        if rng.random() < self.current_epsilon():
            return rng.choice(list(self.arm_ids))
        return self.best_arm()

    def best_arm(self):
        """Highest mean reward. Ties break on declared arm order, so the choice is
        reproducible across runs rather than dependent on dict iteration."""
        return max(self.arm_ids, key=lambda a: (self.average_reward[a],
                                                -self.arm_ids.index(a)))

    # ------------------------------------------------------------------ learning

    def update_reward(self, arm_id, reward):
        """Fold one observed reward into that arm's running mean.

        Incremental mean: mean += (reward - mean) / n. Equivalent to recomputing from
        the full history but O(1) in time and memory, and it cannot drift the way a
        running sum divided by a separately-tracked count can.

        An unknown arm is refused rather than silently created: a typo'd arm id that
        quietly registers itself would dilute the statistics of the real arms and the
        mistake would never surface.
        """
        if arm_id not in self.counts:
            raise KeyError(f"unknown arm id: {arm_id!r}")
        try:
            reward = float(reward)
        except (TypeError, ValueError):
            raise TypeError("reward must be numeric")

        self.counts[arm_id] += 1
        n = self.counts[arm_id]
        self.average_reward[arm_id] += (reward - self.average_reward[arm_id]) / n
        self.steps += 1
        return self.average_reward[arm_id]

    def stats(self):
        """Snapshot for logging/telemetry. Copies so callers cannot mutate state."""
        return {
            "steps": self.steps,
            "epsilon": self.current_epsilon(),
            "counts": dict(self.counts),
            "average_reward": dict(self.average_reward),
            "best_arm": self.best_arm(),
        }

    # ------------------------------------------------------------------ aliases
    # The queued spec for this component named the API `update(arm_id, reward)` and
    # `get_stats()`. The implementation landed as `update_reward` / `stats`, so a
    # caller written against the spec fails with AttributeError at runtime rather
    # than at import. These are thin, documented aliases — one canonical
    # implementation, two names — rather than a second copy of the arithmetic.

    def update(self, arm_id, reward):
        """Alias for `update_reward`. See its docstring for the incremental mean."""
        return self.update_reward(arm_id, reward)

    def get_stats(self):
        """Alias for `stats`. Returns a copied snapshot; callers cannot mutate state."""
        return self.stats()

    def __len__(self):
        return len(self.arm_ids)

    def __repr__(self):
        return (f"BanditSelector(arm_ids={list(self.arm_ids)!r}, "
                f"epsilon={self.epsilon!r}, decay={self.decay!r})")


def choose(db, task_class, prompt, candidates=None):
    candidates = candidates or MODELS
    rows = [r for r in _outcomes(db) if (r.get("kind") or "build") == task_class]
    if len(rows) < 8:                                  # cold start -> heuristic
        return model_router.route(prompt)["model"]
    # ACCEPTANCE GATE. Before spending another exploration draw, ask whether one
    # arm is already ESTABLISHED as better than every rival — not merely ahead.
    # If it is, exploring is no longer buying information, it is buying a worse
    # model at random. If nothing is established, fall straight through to the
    # unchanged epsilon/UCB1 path below.
    if ACCEPTANCE_ENABLED:
        leader = tracker_from_outcomes(db, task_class, candidates).accepted_leader(
            candidates, min_samples=ACCEPT_MIN_SAMPLES)
        if leader:
            return leader
    if random.random() < EPSILON:                      # explore
        return random.choice(candidates)
    stats = {m: [0.0, 0] for m in candidates}          # [sum_reward, n]
    for r in rows:
        m = r.get("model")
        if m in stats:
            stats[m][0] += _reward(r); stats[m][1] += 1
    total = sum(n for _, n in stats.values()) or 1
    best, best_score = candidates[0], -1
    for m, (s, n) in stats.items():
        if n == 0:
            return m                                   # try the untried arm
        ucb = s / n + math.sqrt(2 * math.log(total) / n)   # UCB1
        if ucb > best_score:
            best, best_score = m, ucb
    return best
