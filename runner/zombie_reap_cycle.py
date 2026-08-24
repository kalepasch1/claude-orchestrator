#!/usr/bin/env python3
"""
zombie_reap_cycle.py - the periodic half of zombie disposal.

`zombie_reaper.terminate_expired()` is deliberately detection-free: it takes ids a
caller has already decided are expired and moves them to FAILED. Nothing in the
runner ever called it, so the terminal half of the pipeline existed but never ran —
tasks whose repair budget was exhausted kept being rediscovered by
`runner._reap_zombie_tasks()` every cycle, requeued forever, and never reached a
terminal state.

This module is the missing caller. It owns exactly three things:

  * **detection** — which RUNNING tasks have a heartbeat old enough, and an attempt
    count high enough, that another repair pass is not worth a claim slot.
  * **pacing** — a monotonic interval gate so the runtime can call `run_once()`
    on every scheduler tick without hammering the database.
  * **the on/off switch** — a boolean config flag, so the whole behaviour can be
    turned off fleet-wide without a code change or a deploy.

It does not write task rows itself. Termination stays in `zombie_reaper`, so there
is still exactly one definition of "how a task is terminated".

Config (repo convention: `ORCH_`-prefixed keys read through `config_consumer`, so
they are fleet-pushable via `fleet_control.py`):

    ORCH_ZOMBIE_REAPER_ENABLED         "true" (default). "false" disables the cycle
                                       entirely — `run_once()` becomes a no-op.
    ORCH_ZOMBIE_REAPER_INTERVAL_S      30 (default). Minimum seconds between cycles.
    ORCH_ZOMBIE_REAPER_HEARTBEAT_TTL_S 5400 (default, 90 min). A RUNNING task whose
                                       `updated_at` is older than this is expired.
                                       Deliberately far beyond the 30-minute repair
                                       cutoff in `runner._reap_zombie_tasks()`, so
                                       this only ever disposes of work repair has
                                       already failed to rescue.
    ORCH_ZOMBIE_REAPER_MIN_ATTEMPT     0 (default). Require at least this many prior
                                       attempts before terminating. Raise it to make
                                       disposal strictly an end-of-budget action.
    ORCH_ZOMBIE_REAPER_MAX_PER_CYCLE   25 (default). Cap per cycle so one fleet-wide
                                       outage cannot mass-fail the whole queue.

Usage:
    import zombie_reap_cycle
    result = zombie_reap_cycle.run_once()      # paced; no-op until interval elapses
    result = zombie_reap_cycle.run_once(force=True)   # ignore the interval gate

Every entry point is fail-soft: a broken database, a missing module, or a bad row
returns a result dict describing what happened instead of raising, because this runs
inside the scheduler tick and must never wedge the runner.
"""
import os
import sys
import time
import datetime
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import log as _log_mod
    _log = _log_mod.get("zombie_reap_cycle")
except Exception:  # pragma: no cover - logging must never be the failure
    class _NullLog:
        def _emit(self, *a, **k):
            pass
        info = warning = warn = error = debug = _emit
    _log = _NullLog()

CONFIG_ENABLED = "ZOMBIE_REAPER_ENABLED"
CONFIG_INTERVAL_S = "ZOMBIE_REAPER_INTERVAL_S"
CONFIG_HEARTBEAT_TTL_S = "ZOMBIE_REAPER_HEARTBEAT_TTL_S"
CONFIG_MIN_ATTEMPT = "ZOMBIE_REAPER_MIN_ATTEMPT"
CONFIG_MAX_PER_CYCLE = "ZOMBIE_REAPER_MAX_PER_CYCLE"

DEFAULT_ENABLED = True
DEFAULT_INTERVAL_S = 30
DEFAULT_HEARTBEAT_TTL_S = 5400
DEFAULT_MIN_ATTEMPT = 0
DEFAULT_MAX_PER_CYCLE = 25

RUNNING_STATE = "RUNNING"
REASON = "zombie-reaper: heartbeat expired, repair budget exhausted"

# Accounts owned by an interactive Cowork session heartbeat themselves and are
# released by their own executor. Terminating them from here would fail work that
# is genuinely in flight.
_SKIP_ACCOUNT_PREFIXES = ("cowork-",)


def _cfg():
    """Config reader, resolved late so importing this module cannot fail on it."""
    try:
        import config_consumer
        return config_consumer
    except Exception:
        return None


def _get_bool(key, default):
    cc = _cfg()
    if cc is None:
        raw = os.environ.get(f"ORCH_{key}", "").strip().lower()
        return default if not raw else raw in ("1", "true", "yes", "on")
    try:
        return cc.get_bool(key, default)
    except Exception:
        return default


def _get_int(key, default):
    cc = _cfg()
    if cc is None:
        try:
            return int(os.environ.get(f"ORCH_{key}", "").strip() or default)
        except Exception:
            return default
    try:
        return cc.get_int(key, default)
    except Exception:
        return default


def enabled():
    """True when the reap cycle is switched on. Default on."""
    return _get_bool(CONFIG_ENABLED, DEFAULT_ENABLED)


def interval_s():
    """Seconds between cycles. Non-positive values fall back to the default so a
    bad config push cannot turn this into a hot loop against the database."""
    value = _get_int(CONFIG_INTERVAL_S, DEFAULT_INTERVAL_S)
    return value if value > 0 else DEFAULT_INTERVAL_S


def heartbeat_ttl_s():
    value = _get_int(CONFIG_HEARTBEAT_TTL_S, DEFAULT_HEARTBEAT_TTL_S)
    return value if value > 0 else DEFAULT_HEARTBEAT_TTL_S


def min_attempt():
    value = _get_int(CONFIG_MIN_ATTEMPT, DEFAULT_MIN_ATTEMPT)
    return value if value >= 0 else DEFAULT_MIN_ATTEMPT


def max_per_cycle():
    value = _get_int(CONFIG_MAX_PER_CYCLE, DEFAULT_MAX_PER_CYCLE)
    return value if value > 0 else DEFAULT_MAX_PER_CYCLE


def _parse_ts(value):
    """ISO-8601 -> aware datetime, or None when the value cannot be read."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed


def _is_older_than(timestamp, cutoff_iso):
    """Fail-soft staleness test.

    The timestamp is parsed here *before* anything else runs, because an
    unreadable value must mean "not stale". `common_utils.is_older_than` answers
    True for garbage input — reasonable for a requeue, dangerous for a terminal
    FAILED write — so this never terminates a task on the strength of a heartbeat
    it could not read. Once the value parses, the shared helper does the compare so
    there is still one definition of staleness in the fleet.
    """
    stamp = _parse_ts(timestamp)
    if stamp is None:
        return False
    try:
        import common_utils
        return bool(common_utils.is_older_than(str(timestamp).strip(), cutoff_iso))
    except Exception:
        pass
    cutoff = _parse_ts(cutoff_iso)
    if cutoff is None:
        return False
    return stamp < cutoff


class ZombieReapCycle:
    """Paced detection + termination against an injectable store and reaper.

    `store` is any object with `select(table, params)` / `update(table, match, patch)`
    — exactly `runner/db.py`'s surface, so production passes `db` and tests pass an
    in-memory fake. `reaper` is anything exposing `terminate_expired(ids, reason=,
    store=)`; it defaults to the `zombie_reaper` module singleton.
    """

    def __init__(self, store=None, reaper=None, clock=None):
        self._lock = threading.Lock()
        self._store = store
        self._reaper = reaper
        self._clock = clock or time.monotonic
        self._last_run = 0.0
        self._ran_once = False

    # ------------------------------------------------------------ collaborators

    def _resolve_store(self, store=None):
        if store is not None:
            return store
        if self._store is not None:
            return self._store
        import db as _db
        self._store = _db
        return self._store

    def _resolve_reaper(self):
        if self._reaper is not None:
            return self._reaper
        import zombie_reaper as _zr
        self._reaper = _zr
        return self._reaper

    # ------------------------------------------------------------------ pacing

    def due(self):
        """True when at least `interval_s()` has elapsed since the last cycle.
        The first call is always due, so a freshly started runner reaps promptly
        instead of waiting out one full interval."""
        try:
            if not self._ran_once:
                return True
            return (self._clock() - self._last_run) >= interval_s()
        except Exception:
            return False

    # --------------------------------------------------------------- detection

    def detect(self, store=None):
        """Ids of RUNNING tasks whose heartbeat has expired past the repair budget.

        Returns [] rather than raising on any store failure — a detection outage
        must degrade to "terminate nothing", never to a crashed scheduler tick.
        """
        try:
            store = self._resolve_store(store)
        except Exception as e:
            _log.warning("zombie-reap-cycle: no task store available (%s); detected nothing", e)
            return []

        ttl = heartbeat_ttl_s()
        floor = min_attempt()
        cap = max_per_cycle()
        cutoff = (datetime.datetime.now(datetime.timezone.utc)
                  - datetime.timedelta(seconds=ttl)).isoformat()

        try:
            rows = store.select("tasks", {
                "select": "id,slug,state,updated_at,attempt,account",
                "state": f"eq.{RUNNING_STATE}",
                "order": "updated_at.asc",
                "limit": "250",
            }) or []
        except Exception as e:
            _log.warning("zombie-reap-cycle: could not read RUNNING tasks (%s); detected nothing", e)
            return []

        expired = []
        for row in rows:
            try:
                task_id = str(row.get("id") or "").strip()
                if not task_id:
                    continue
                account = str(row.get("account") or "")
                if any(account.startswith(p) for p in _SKIP_ACCOUNT_PREFIXES):
                    continue
                try:
                    attempt = int(row.get("attempt") or 0)
                except (TypeError, ValueError):
                    attempt = 0
                if attempt < floor:
                    continue
                if not _is_older_than(row.get("updated_at"), cutoff):
                    continue
                expired.append(task_id)
                if len(expired) >= cap:
                    break
            except Exception:
                continue
        return expired

    # ----------------------------------------------------------------- the tick

    def run_once(self, store=None, force=False):
        """One paced detection + termination cycle.

        Result keys:
            ran         did detection actually execute this call
            reason      why not, when `ran` is False ("disabled" / "not-due")
            detected    ids detection selected
            terminated / skipped / missing / errored  passthrough from the reaper
        """
        result = {"ran": False, "reason": "", "detected": [],
                  "terminated": [], "skipped": [], "missing": [], "errored": []}
        try:
            if not enabled():
                result["reason"] = "disabled"
                return result

            with self._lock:
                if not force and not self.due():
                    result["reason"] = "not-due"
                    return result
                try:
                    self._last_run = self._clock()
                except Exception:
                    self._last_run = 0.0
                self._ran_once = True

            result["ran"] = True
            expired = self.detect(store=store)
            result["detected"] = list(expired)
            if not expired:
                return result

            try:
                reaper = self._resolve_reaper()
                outcome = reaper.terminate_expired(expired, reason=REASON,
                                                   store=store or self._store) or {}
            except Exception as e:
                _log.warning("zombie-reap-cycle: termination failed (%s); %d ids left RUNNING",
                             e, len(expired))
                result["errored"] = list(expired)
                return result

            for key in ("terminated", "skipped", "missing", "errored"):
                result[key] = list(outcome.get(key) or [])
            if result["terminated"]:
                _log.warning("zombie-reap-cycle: terminated %d expired task(s)",
                             len(result["terminated"]))
            return result
        except Exception as e:  # pragma: no cover - last-resort fail-soft
            _log.warning("zombie-reap-cycle: cycle error (%s); nothing terminated", e)
            result["reason"] = "error"
            return result


# ---------------------------------------------------------------------------
# Module-level singleton (repo convention: module functions delegate to one
# thread-safe instance). Constructed with no store or reaper; both are resolved
# lazily on first use so importing this module opens no connection.
# ---------------------------------------------------------------------------
_cycle = ZombieReapCycle()


def run_once(store=None, force=False):
    """Run one paced zombie reap cycle. Never raises."""
    return _cycle.run_once(store=store, force=force)


def detect(store=None):
    """Ids currently eligible for termination. Never raises."""
    return _cycle.detect(store=store)


def due():
    """True when the next cycle is due. Never raises."""
    return _cycle.due()


def reset():
    """Clear the pacing state. Test seam; also useful after a config push."""
    try:
        _cycle._last_run = 0.0
        _cycle._ran_once = False
    except Exception:
        pass


def stats():
    """Observable state, so operators and tests can see the cycle's configuration."""
    try:
        return {
            "enabled": enabled(),
            "interval_s": interval_s(),
            "heartbeat_ttl_s": heartbeat_ttl_s(),
            "min_attempt": min_attempt(),
            "max_per_cycle": max_per_cycle(),
            "ran_once": bool(_cycle._ran_once),
        }
    except Exception:
        return {}


if __name__ == "__main__":  # pragma: no cover - manual operator invocation
    import json
    print(json.dumps(run_once(force=True), indent=2, default=str))
