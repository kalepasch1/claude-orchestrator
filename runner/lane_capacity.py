#!/usr/bin/env python3
"""lane_capacity.py - decide whether a coder lane can actually do work BEFORE a task is claimed.

ROOT CAUSE (queue outage, runner logs): two DIFFERENT faults were collapsed into one
reactive code path. `account_pool.mark_exhausted` is only reached AFTER a task has been
claimed, dispatched, and has failed — and it applies the same exponential cooldown to
every cause. During the outage the logs carried both:

    "weekly limit reached - resets ..."          (capacity: real, time-bounded, self-healing)
    "OAuth session expired and could not be refreshed"  (credential: needs the OPERATOR)

Treated identically, both looked like "cool down 20 minutes and retry". The weekly-capped
account was re-probed every 20 minutes for days, and the expired-OAuth account was picked
again on every cycle — each pick burning one `attempt` off a real task, so tasks marched to
BLOCKED for a reason that had nothing to do with the task.

This module adds the missing pre-claim gate:

  classify(text)      one failure string -> one of the CAUSE_* states, so weekly exhaustion,
                      unrefreshable OAuth and a transient blip are never confused again.
  probe(account)      ACTIVE credential probe (cheap, cached) — asks the lane whether it can
                      work instead of discovering it through a burned task.
  quarantine(...)     cool down ONLY the unhealthy account, for a duration that matches the
                      cause (see _COOLDOWN_BY_CAUSE), recording the cause and reset time.
  healthy_lane()      a lane whose capacity was VERIFIED, not merely not-yet-known-bad.
  should_claim()      the gate: (False, reason) pauses claiming when no lane is healthy.
  preserves_attempt() True when a failure is the fleet's fault, so the caller must NOT
                      charge the task an attempt.
  capacity_state()    operator-facing state: cause, reset time, required action.

Conventions (CLAUDE.md): module-level singleton with delegating module functions,
fail-soft everywhere (a bug in the gate must never wedge the runner — on internal error
we allow claiming rather than stalling the fleet), all tunables ORCH_-prefixed env vars so
they are fleet-pushable via fleet_control.py, and NO credential material is ever logged or
returned — only the env-var NAME and the account name.
"""
import logging
import os
import re
import threading
import time

log = logging.getLogger(__name__)

# --- Causes -----------------------------------------------------------------
# Deliberately separate constants rather than a bare string: callers branch on these,
# and the whole point of the module is that these three are NOT the same thing.
CAUSE_HEALTHY = "healthy"
CAUSE_WEEKLY_LIMIT = "weekly_limit"      # capacity exhausted; clears on its own at reset
CAUSE_OAUTH_EXPIRED = "oauth_expired"    # credential dead; ONLY an operator can clear it
CAUSE_TRANSIENT = "transient"            # network/5xx/overloaded; retry shortly
CAUSE_UNKNOWN = "unknown"

# Cooldown per cause, in seconds. A weekly cap is not worth re-probing every 20 minutes and
# an expired OAuth session is not worth re-probing at all until someone re-authenticates, but
# we still re-check it eventually in case the operator fixed it without telling us.
_COOLDOWN_BY_CAUSE = {
    CAUSE_WEEKLY_LIMIT: ("ORCH_LANE_WEEKLY_COOLDOWN", 6 * 3600),
    CAUSE_OAUTH_EXPIRED: ("ORCH_LANE_OAUTH_COOLDOWN", 30 * 60),
    CAUSE_TRANSIENT: ("ORCH_LANE_TRANSIENT_COOLDOWN", 120),
    CAUSE_UNKNOWN: ("ORCH_LANE_UNKNOWN_COOLDOWN", 20 * 60),
}

# Operator action per cause. Surfaced by capacity_state() so the human reads what to DO,
# not a stack trace. Empty string = nothing for a human to do; it heals itself.
_ACTION_BY_CAUSE = {
    CAUSE_HEALTHY: "",
    CAUSE_WEEKLY_LIMIT: "wait for the plan reset, or add capacity (another authorized account)",
    CAUSE_OAUTH_EXPIRED: "re-authenticate this account: run `claude login` for its CLAUDE_CONFIG_DIR",
    CAUSE_TRANSIENT: "",
    CAUSE_UNKNOWN: "inspect the lane log; cause was not recognized",
}

# Ordered most-specific first: an OAuth failure that also mentions "limit" is still an OAuth
# failure, so the credential patterns must win over the capacity patterns.
_OAUTH_PATTERNS = (
    r"oauth (?:token|session)[^.\n]*(?:expired|invalid|revoked)",
    r"(?:expired|invalid|revoked)[^.\n]*oauth",
    r"could not be refreshed",
    r"refresh token[^.\n]*(?:expired|invalid|failed|rejected)",
    r"failed to authenticate",
    r"authentication[^.\n]*(?:failed|expired)",
    r"re-?authenticat",
    r"please (?:run )?`?claude login`?",
    r"\b401\b",
    r"invalid_grant",
    r"unauthorized",
)
_WEEKLY_PATTERNS = (
    r"weekly limit",
    r"hit your weekly",
    r"usage limit",
    r"limit reached",
    r"limit[^\n]{0,12}resets",
    r"out of credits",
    r"insufficient_quota",
    r"credit balance is too low",
    r"monthly (?:limit|spend)",
    r"upgrade to increase",
    r"quota",
)
_TRANSIENT_PATTERNS = (
    r"\b(?:429|500|502|503|504)\b",
    r"\boverloaded\b",
    r"rate.?limit",
    r"timed? ?out",
    r"connection (?:reset|refused|error)",
    r"temporarily unavailable",
    r"try again",
    r"\bECONNRESET\b",
)

_OAUTH_RX = re.compile("|".join(_OAUTH_PATTERNS), re.I)
_WEEKLY_RX = re.compile("|".join(_WEEKLY_PATTERNS), re.I)
_TRANSIENT_RX = re.compile("|".join(_TRANSIENT_PATTERNS), re.I)

# "resets at 3pm", "resets 2026-08-12T09:00Z", "Resets in 4h 12m" — best-effort only.
_RESET_RX = re.compile(
    r"resets?\s*(?:at|on|in)?\s*[:·-]?\s*([0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9:]+Z?|"
    r"[0-9]{1,2}\s*h(?:ours?)?(?:\s*[0-9]{1,2}\s*m)?|[0-9]{1,2}[:.][0-9]{2}\s*(?:am|pm)?)",
    re.I,
)

# Causes that mean "this lane cannot work now". CAUSE_HEALTHY and CAUSE_UNKNOWN are not here:
# unknown is not proof of failure, and refusing to claim on it would stall on any odd log line.
_BLOCKING = (CAUSE_WEEKLY_LIMIT, CAUSE_OAUTH_EXPIRED, CAUSE_TRANSIENT)


def _int_env(name, default):
    """Read an int env var at call time so fleet_control hot-pushes take effect."""
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return int(default)


def cooldown_for(cause):
    """Seconds an account with this cause should stay quarantined. Fail-soft: never raises."""
    name, default = _COOLDOWN_BY_CAUSE.get(cause, _COOLDOWN_BY_CAUSE[CAUSE_UNKNOWN])
    return max(0, _int_env(name, default))


def action_for(cause):
    """Operator instruction for a cause, or "" when it self-heals."""
    return _ACTION_BY_CAUSE.get(cause, _ACTION_BY_CAUSE[CAUSE_UNKNOWN])


def classify(text):
    """Classify a lane failure string into a CAUSE_*.

    Credential failures are checked FIRST: a dead OAuth session frequently prints alongside
    limit-ish wording, and mistaking it for capacity is exactly the bug this module fixes.
    Fail-soft: any input (None, bytes, objects) yields a cause, never an exception.
    """
    try:
        s = text.decode("utf-8", "replace") if isinstance(text, (bytes, bytearray)) else str(text or "")
    except Exception:
        return CAUSE_UNKNOWN
    if not s.strip():
        return CAUSE_HEALTHY
    if _OAUTH_RX.search(s):
        return CAUSE_OAUTH_EXPIRED
    if _WEEKLY_RX.search(s):
        return CAUSE_WEEKLY_LIMIT
    if _TRANSIENT_RX.search(s):
        return CAUSE_TRANSIENT
    return CAUSE_UNKNOWN


def parse_reset(text):
    """Best-effort reset marker from a provider message. Returns the raw string or None.

    Deliberately NOT parsed into a timestamp: provider wording is unstable and a wrong
    timestamp is worse than a quoted one. The operator reads it; the cooldown does the work.
    """
    try:
        m = _RESET_RX.search(str(text or ""))
        return m.group(1).strip() if m else None
    except Exception:
        return None


def preserves_attempt(cause):
    """True when a failure is the FLEET's fault and must not be charged to the task.

    Weekly exhaustion, a dead credential and a transient provider blip say nothing about
    whether the task is doable, so the caller must decrement/skip the attempt counter.
    """
    return cause in _BLOCKING


class LaneCapacity:
    """Verified-capacity view over the account pool. Thread-safe; probes are cached.

    Holds no credential material: probe results record the account NAME and the env-var
    NAME only. `_state` maps account name -> {cause, until, reset, checked_at, detail}.
    """

    def __init__(self, pool=None):
        self._lock = threading.Lock()
        self._state = {}
        self._pool = pool
        self._paused_since = None

    # -- pool access ---------------------------------------------------------
    def _accounts(self):
        """All configured accounts. Fail-soft: [] when the pool is unavailable."""
        try:
            pool = self._pool
            if pool is None:
                import account_pool
                pool = account_pool.AccountPool()
                self._pool = pool
            return list(getattr(pool, "accts", None) or [])
        except Exception as exc:
            log.debug("lane_capacity: pool unavailable (%s); fail-soft to no accounts", exc)
            return []

    def _pool_healthy(self, acct):
        """Whether account_pool itself considers the account out of cooldown."""
        try:
            return bool(self._pool._healthy(acct))
        except Exception:
            return True  # fail-soft: pool opinion missing must not quarantine a good lane

    # -- probing -------------------------------------------------------------
    def probe(self, acct, force=False):
        """Actively check whether one account can work. Returns a redacted result dict.

        Cached for ORCH_LANE_PROBE_TTL seconds (default 300) so the pre-claim gate is cheap
        enough to run on every claim. `force=True` bypasses the cache. Fail-soft: an
        unprobeable account is reported CAUSE_UNKNOWN and stays claimable — refusing work
        because the probe broke would be worse than the failure it guards against.
        """
        name = (acct or {}).get("name") or "unknown"
        now = time.time()
        ttl = _int_env("ORCH_LANE_PROBE_TTL", 300)
        with self._lock:
            cached = self._state.get(name)
            if cached and not force:
                if now < cached.get("until", 0):
                    return dict(cached, cached=True)          # still quarantined
                if now - cached.get("checked_at", 0) < ttl and cached.get("cause") == CAUSE_HEALTHY:
                    return dict(cached, cached=True)          # recently verified healthy
        cause, detail = self._run_probe(acct)
        result = self._record(name, cause, detail=detail)
        return dict(result, cached=False)

    def _run_probe(self, acct):
        """The actual credential check. Returns (cause, detail). Never raises.

        Order matters and each step is cheap:
          1. account_pool cooldown — already known bad, do not spend a probe on it
          2. api-type rows: the key env var must actually be populated, otherwise
             `env_for` silently withholds it and the CLI falls back to the exhausted login
          3. login-type rows: the CLAUDE_CONFIG_DIR must exist and hold credentials; a
             missing/empty credentials file IS an expired-OAuth condition
          4. an injectable custom probe (ORCH_LANE_PROBE_HOOK) for deployments that want
             a live round-trip; its output is classified through classify()
        """
        try:
            if not self._pool_healthy(acct):
                return CAUSE_WEEKLY_LIMIT, "account_pool reports this account cooling down"
            kind = (acct or {}).get("type") or "login"
            if kind == "api":
                var = (acct or {}).get("api_key_env") or "ANTHROPIC_API_KEY"
                if not os.environ.get(var):
                    # Report the VARIABLE NAME, never the value.
                    return CAUSE_OAUTH_EXPIRED, f"api key env {var} is unset"
            else:
                cfg = (acct or {}).get("config_dir")
                if cfg:
                    cfg = os.path.expanduser(cfg)
                    if not os.path.isdir(cfg):
                        return CAUSE_OAUTH_EXPIRED, "config_dir missing"
                    creds = os.path.join(cfg, ".credentials.json")
                    if os.path.exists(creds) and os.path.getsize(creds) == 0:
                        return CAUSE_OAUTH_EXPIRED, "credentials file is empty"
            hook = os.environ.get("ORCH_LANE_PROBE_HOOK", "")
            if hook:
                out = self._call_hook(hook, acct)
                if out is not None:
                    return classify(out), "probe hook"
            return CAUSE_HEALTHY, "probe passed"
        except Exception as exc:
            log.debug("lane_capacity: probe error (%s); fail-soft to unknown", exc)
            return CAUSE_UNKNOWN, "probe error"

    def _call_hook(self, hook, acct):
        """Run an operator-supplied probe command. Returns its output text or None."""
        try:
            import subprocess
            env = dict(os.environ)
            env["ORCH_PROBE_ACCOUNT"] = (acct or {}).get("name") or ""
            proc = subprocess.run(["bash", "-lc", hook], capture_output=True, text=True,
                                  timeout=_int_env("ORCH_LANE_PROBE_TIMEOUT", 20), env=env)
            return (proc.stdout or "") + (proc.stderr or "")
        except Exception as exc:
            log.debug("lane_capacity: probe hook failed (%s)", exc)
            return None

    # -- quarantine ----------------------------------------------------------
    def _record(self, name, cause, detail="", reset=None):
        entry = {
            "account": name,
            "cause": cause,
            "detail": detail,
            "reset": reset,
            "action": action_for(cause),
            "checked_at": time.time(),
            "until": time.time() + cooldown_for(cause) if cause in _BLOCKING else 0,
        }
        with self._lock:
            self._state[name] = entry
        return dict(entry)

    def quarantine(self, acct, text="", cause=None):
        """Quarantine ONLY this account, for a duration matching the cause.

        Also forwards to account_pool.mark_exhausted so existing rotation/notification keeps
        working — but ONLY for capacity causes. Marking a dead credential "exhausted" is what
        made the pool re-offer it on a 20-minute clock; here it is held out for its own,
        longer window and reported with the operator action instead.
        """
        name = (acct or {}).get("name") or "unknown"
        cause = cause or classify(text)
        entry = self._record(name, cause, detail="quarantined", reset=parse_reset(text))
        if cause == CAUSE_WEEKLY_LIMIT:
            try:
                self._pool.mark_exhausted(acct)
            except Exception as exc:
                log.debug("lane_capacity: mark_exhausted forward failed (%s)", exc)
        log.warning("lane_capacity: account %s quarantined cause=%s reset=%s action=%s",
                    name, cause, entry.get("reset") or "-", entry.get("action") or "-")
        return entry

    def clear(self, acct=None):
        """Release quarantine for one account, or all of them. Used after re-auth/reset."""
        name = (acct or {}).get("name") if isinstance(acct, dict) else acct
        with self._lock:
            if name:
                self._state.pop(name, None)
            else:
                self._state.clear()
            self._paused_since = None

    # -- routing -------------------------------------------------------------
    def is_healthy(self, acct):
        """True when this account probed healthy (or is not known bad)."""
        return self.probe(acct).get("cause") not in _BLOCKING

    def healthy_lane(self):
        """Return the first account with VERIFIED capacity, or None when every lane is down.

        Subscription rows are preferred over api rows, matching account_pool.current()'s
        rule that paid credits are never touched while free subscription capacity exists.
        """
        accounts = self._accounts()
        subs = [a for a in accounts if (a or {}).get("type") != "api"]
        for group in (subs, accounts):
            for acct in group:
                if self.is_healthy(acct):
                    return acct
        return None

    def should_claim(self):
        """The pre-claim gate. Returns (ok, reason).

        (False, reason) means: claim NOTHING this cycle. Pausing costs one idle cycle;
        claiming into a dead lane costs a real task one attempt, which is unrecoverable.
        Fail-soft: with no accounts configured at all we allow claiming (single implicit
        default login), because a mis-read config must not stop the fleet.
        """
        try:
            accounts = self._accounts()
            if not accounts:
                return True, "no account pool configured; claiming allowed"
            lane = self.healthy_lane()
            if lane:
                with self._lock:
                    self._paused_since = None
                return True, "healthy lane: %s" % (lane.get("name") or "unknown")
            causes = sorted({e["cause"] for e in self._state.values() if e["cause"] in _BLOCKING})
            with self._lock:
                if self._paused_since is None:
                    self._paused_since = time.time()
            return False, "no healthy lane (%s); claiming paused to preserve task attempts" % (
                ", ".join(causes) or "unknown")
        except Exception as exc:
            log.debug("lane_capacity: should_claim error (%s); allowing claim", exc)
            return True, "gate error; claiming allowed"

    # -- observability -------------------------------------------------------
    def capacity_state(self):
        """Operator-facing state. Contains NO credential material — names and causes only."""
        accounts = self._accounts()
        now = time.time()
        lanes = []
        for acct in accounts:
            name = (acct or {}).get("name") or "unknown"
            entry = self._state.get(name, {})
            cause = entry.get("cause", CAUSE_UNKNOWN)
            lanes.append({
                "account": name,
                "type": (acct or {}).get("type") or "login",
                "cause": cause,
                "healthy": cause not in _BLOCKING,
                "reset": entry.get("reset"),
                "cooldown_remaining_s": max(0, int(entry.get("until", 0) - now)),
                "action": entry.get("action") or action_for(cause),
                "detail": entry.get("detail", ""),
            })
        healthy = [x for x in lanes if x["healthy"]]
        actions = sorted({x["action"] for x in lanes if not x["healthy"] and x["action"]})
        # Keep paused_since consistent with claiming_paused: an operator may read this
        # state before the next should_claim() cycle runs, and "paused, since never" is
        # a contradiction that hides how long the fleet has actually been stalled.
        with self._lock:
            if lanes and not healthy:
                if self._paused_since is None:
                    self._paused_since = now
            else:
                self._paused_since = None
        return {
            "total_lanes": len(lanes),
            "healthy_lanes": len(healthy),
            "claiming_paused": bool(lanes) and not healthy,
            "paused_since": self._paused_since,
            "operator_actions": actions,
            "lanes": lanes,
        }

    def stats(self):
        """Alias kept for parity with account_pool.stats() (CLAUDE.md convention)."""
        return self.capacity_state()

    def invalidate(self, name=None):
        """Force the next probe to re-check (CLAUDE.md convention)."""
        self.clear(name)


# --- Module-level singleton + delegating functions (CLAUDE.md convention) ----
_lock = threading.Lock()
_capacity = None


def _get():
    global _capacity
    with _lock:
        if _capacity is None:
            _capacity = LaneCapacity()
        return _capacity


def probe(acct, force=False):
    return _get().probe(acct, force=force)


def quarantine(acct, text="", cause=None):
    return _get().quarantine(acct, text=text, cause=cause)


def healthy_lane():
    return _get().healthy_lane()


def should_claim():
    return _get().should_claim()


def capacity_state():
    return _get().capacity_state()


def stats():
    return _get().stats()


def clear(acct=None):
    return _get().clear(acct)


def invalidate(name=None):
    return _get().invalidate(name)


if __name__ == "__main__":
    import json
    ok, why = should_claim()
    print("should_claim:", ok, "-", why)
    print(json.dumps(capacity_state(), indent=2, default=str))
