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
