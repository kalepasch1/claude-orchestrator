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
import math, time, random, os
import model_router

MODELS = [model_router.HAIKU, model_router.SONNET, model_router.OPUS]
EPSILON = float(os.environ.get("BANDIT_EPSILON", "0.1"))
_cache = {"t": 0, "rows": []}


def _env(name, default):
    """ORCH_-prefixed first, legacy BANDIT_ name second, then the default.

    Per CLAUDE.md, fleet-wide tunables must be ORCH_-prefixed so fleet_control.py can
    push them to every machine. These knobs were originally written as BANDIT_*, which
    is not fleet-pushable, so the ORCH_ name is now canonical. The legacy name is still
    read so any machine already carrying it keeps its setting instead of silently
    reverting to the default on the deploy that lands this.
    """
    return os.environ.get(f"ORCH_BANDIT_{name}", os.environ.get(f"BANDIT_{name}", default))


# Acceptance gate. UCB1 alone never stops exploring: it keeps paying the epsilon toll on
# an arm long after the data has settled the question. An acceptance decision is the
# missing piece — once one arm's confidence interval clears another's with enough samples
# behind both, the comparison is decided and exploration on that pair is waste.
ACCEPTANCE_MIN_SAMPLES = int(_env("ACCEPT_MIN_SAMPLES", "12"))
ACCEPTANCE_CONFIDENCE = float(_env("ACCEPT_CONFIDENCE", "0.95"))
# Kill switch: with this off, choose() behaves exactly as it did before the gate existed.
ACCEPTANCE_ENABLED = str(_env("ACCEPTANCE", "true")).lower() in ("1", "true", "yes", "on")

# Two-sided z for the normal approximation. A t-distribution would be marginally tighter
# at small n, but ACCEPTANCE_MIN_SAMPLES already keeps us out of the range where the
# difference decides anything, and this keeps the module dependency-free.
_Z = {0.80: 1.2816, 0.90: 1.6449, 0.95: 1.9600, 0.98: 2.3263, 0.99: 2.5758}


def _z_for(confidence):
    """Nearest tabulated two-sided z. Unknown/absurd input falls back to 95%."""
    try:
        c = float(confidence)
    except (TypeError, ValueError):
        return _Z[0.95]
    if not 0.0 < c < 1.0:
        return _Z[0.95]
    return _Z[min(_Z, key=lambda k: abs(k - c))]


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


class PerformanceTracker:
    """Per-arm reward log with mean and confidence-interval statistics.

    Deliberately holds the raw rewards rather than only running sums: the sums answer
    "which arm looks best", and only the samples answer "is that difference real". The
    acceptance decision needs the second question, which is why this exists.

    Pure and dependency-free — no DB, no clock, no global state. Callers feed it rewards
    (see tracker_from_outcomes for the outcomes-table path).
    """

    def __init__(self, confidence=None, max_samples=None):
        self._rewards = {}
        self.confidence = ACCEPTANCE_CONFIDENCE if confidence is None else float(confidence)
        # Bound memory: an arm observed for months must not grow without limit. Keeps the
        # most RECENT samples, since a model's behavior drifts as the fleet changes.
        self.max_samples = int(max_samples or _env("TRACKER_MAX_SAMPLES", "2000"))

    # --- logging --------------------------------------------------------------------
    def record(self, arm, reward):
        """Log one reward for one arm. Non-numeric rewards are ignored, not raised on."""
        try:
            value = float(reward)
        except (TypeError, ValueError):
            return False
        if value != value or value in (float("inf"), float("-inf")):   # NaN / inf
            return False
        bucket = self._rewards.setdefault(arm, [])
        bucket.append(value)
        if len(bucket) > self.max_samples:
            del bucket[:len(bucket) - self.max_samples]
        return True

    def extend(self, arm, rewards):
        """Log many rewards for one arm. Returns how many were accepted."""
        return sum(1 for r in (rewards or []) if self.record(arm, r))

    def reset(self, arm=None):
        """Forget one arm, or all of them."""
        if arm is None:
            self._rewards.clear()
        else:
            self._rewards.pop(arm, None)

    # --- statistics -----------------------------------------------------------------
    def arms(self):
        """Arms with at least one observation, best mean first."""
        return sorted(self._rewards, key=lambda a: (-(self.mean(a) or 0.0), str(a)))

    def n(self, arm):
        return len(self._rewards.get(arm, ()))

    def total(self, arm):
        return sum(self._rewards.get(arm, ()))

    def rewards(self, arm):
        """Copy of the logged rewards — callers must not mutate our state."""
        return list(self._rewards.get(arm, ()))

    def mean(self, arm):
        """Mean reward, or None when the arm has never been observed."""
        count = self.n(arm)
        return (self.total(arm) / count) if count else None

    def variance(self, arm):
        """SAMPLE variance (n-1). None below two observations, where it is undefined —
        returning 0.0 there would claim certainty from a single data point."""
        samples = self._rewards.get(arm, ())
        count = len(samples)
        if count < 2:
            return None
        mu = sum(samples) / count
        return sum((s - mu) ** 2 for s in samples) / (count - 1)

    def stddev(self, arm):
        var = self.variance(arm)
        return None if var is None else math.sqrt(var)

    def stderr(self, arm):
        """Standard error of the mean. None below two observations."""
        sd = self.stddev(arm)
        return None if sd is None else sd / math.sqrt(self.n(arm))

    def confidence_interval(self, arm, confidence=None):
        """(low, high) for the arm's mean reward, or None below two observations.

        Normal approximation: mean +/- z * stderr. A zero-variance arm yields a
        degenerate interval equal to its mean, which is the honest answer for identical
        observations rather than an invented width.
        """
        se = self.stderr(arm)
        if se is None:
            return None
        mu = self.mean(arm)
        half = _z_for(self.confidence if confidence is None else confidence) * se
        return (mu - half, mu + half)

    def summary(self):
        """Per-arm stats, suitable for logging or an operator view."""
        out = {}
        for arm in self._rewards:
            ci = self.confidence_interval(arm)
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

    def best(self, candidates=None):
        """Highest-mean observed arm among candidates, or None if none were observed."""
        pool = [a for a in self._rewards if candidates is None or a in candidates]
        pool = [a for a in pool if self.n(a) > 0]
        if not pool:
            return None
        return max(pool, key=lambda a: (self.mean(a), self.n(a)))

    # --- acceptance decision --------------------------------------------------------
    def acceptance(self, arm, baseline, min_samples=None, confidence=None):
        """Is `arm` established as better than `baseline`? Returns a verdict dict.

        Accepts only when BOTH arms clear min_samples AND arm's confidence-interval low
        bound sits above baseline's high bound — non-overlapping intervals. That is a
        deliberately conservative bar: a higher mean on thin or noisy data is exactly the
        signal that makes a bandit lock onto a lucky arm, so "looks better" is not enough.

        Keys: accepted (bool), reason (str), plus the means/CIs/n behind the call.
        """
        floor = ACCEPTANCE_MIN_SAMPLES if min_samples is None else int(min_samples)
        n_arm, n_base = self.n(arm), self.n(baseline)
        arm_mean, base_mean = self.mean(arm), self.mean(baseline)
        arm_ci = self.confidence_interval(arm, confidence)
        base_ci = self.confidence_interval(baseline, confidence)
        verdict = {"arm": arm, "baseline": baseline, "n": n_arm, "baseline_n": n_base,
                   "mean": arm_mean, "baseline_mean": base_mean,
                   "ci": arm_ci, "baseline_ci": base_ci, "accepted": False}

        if arm == baseline:
            verdict["reason"] = "arm and baseline are the same arm"
            return verdict
        if n_arm < floor or n_base < floor:
            verdict["reason"] = (f"insufficient samples: n={n_arm}, baseline_n={n_base}, "
                                 f"need {floor} each")
            return verdict
        if arm_ci is None or base_ci is None:
            verdict["reason"] = "no confidence interval available"
            return verdict
        if arm_ci[0] > base_ci[1]:
            verdict["accepted"] = True
            verdict["reason"] = (f"ci low {arm_ci[0]:.4f} exceeds baseline ci high "
                                 f"{base_ci[1]:.4f}")
            return verdict
        verdict["reason"] = (f"intervals overlap: [{arm_ci[0]:.4f}, {arm_ci[1]:.4f}] vs "
                             f"[{base_ci[0]:.4f}, {base_ci[1]:.4f}]")
        return verdict

    def accepts(self, arm, baseline, min_samples=None, confidence=None):
        """Boolean form of acceptance()."""
        return bool(self.acceptance(arm, baseline, min_samples, confidence)["accepted"])

    def accepted_leader(self, candidates=None, min_samples=None, confidence=None):
        """The arm established as better than EVERY other candidate, else None.

        None is the common and correct answer: it means the data has not settled the
        question yet, so the caller should keep exploring.
        """
        pool = [a for a in self._rewards if candidates is None or a in candidates]
        pool = [a for a in pool if self.n(a) > 0]
        if len(pool) < 2:
            return None
        leader = self.best(pool)
        for other in pool:
            if other != leader and not self.accepts(leader, other, min_samples, confidence):
                return None
        return leader


def tracker_from_outcomes(db, task_class, candidates=None):
    """Build a PerformanceTracker from the outcomes table for one task class.

    One place converts outcome rows into rewards, so choose(), the acceptance gate and
    any operator view all read the same numbers instead of three re-derivations.
    """
    tracker = PerformanceTracker()
    for r in _outcomes(db):
        if (r.get("kind") or "build") != task_class:
            continue
        model = r.get("model")
        if candidates is not None and model not in candidates:
            continue
        tracker.record(model, _reward(r))
    return tracker


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

    # ACCEPTANCE GATE, before exploration. UCB1 plus an epsilon floor explores forever;
    # once one arm's confidence interval clears every rival's, with ACCEPTANCE_MIN_SAMPLES
    # behind each, the comparison is settled and further exploration only spends money to
    # re-learn it. Conservative by construction: a merely higher mean does not qualify, so
    # this cannot lock onto a lucky arm. Returns None while the data is still ambiguous —
    # the usual case — and then the original UCB1 path below runs untouched.
    if ACCEPTANCE_ENABLED:
        leader = tracker_from_outcomes(db, task_class, candidates).accepted_leader(candidates)
        if leader is not None:
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
