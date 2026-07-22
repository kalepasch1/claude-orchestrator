#!/usr/bin/env python3
"""
account_pool.py - keep projects moving when one account/credential hits its cap by
rotating to the NEXT credential you've configured.

IMPORTANT / honest note: only add credentials you are AUTHORIZED to use (e.g. your
own Pro/Max login plus your own Team or API-billing org). This rotates among YOUR
accounts to avoid downtime - it is not a tool for evading limits with throwaway
accounts, and you should stay within Anthropic's usage policies.

Config: ~/.claude-orchestrator/accounts.json
[
  {"name":"personal-max", "type":"login", "config_dir":"~/.claude"},
  {"name":"team-api",     "type":"api",   "api_key_env":"ANTHROPIC_API_KEY_TEAM"}
]
Each entry maps to either a Claude Code login profile (its own CLAUDE_CONFIG_DIR) or
an API key. On usage-exhaustion the pool marks the current one cooling-down (default
4h) and returns the next healthy one.

API:
  pool = AccountPool()
  acct = pool.current()                 # -> dict or None
  env  = pool.env_for(acct)             # -> dict to merge into subprocess env
  pool.mark_exhausted(acct)             # call on "usage limit" -> rotates
  pool.mark_ok(acct)
"""
import os, json, time

HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
CFG = os.path.join(HOME, "accounts.json")
# Default cooldown period (seconds) before a rate-limited account becomes eligible again.
DEFAULT_COOLDOWN_SECS = 4 * 3600  # 4 hours
STATE = os.path.join(HOME, "accounts_state.json")
# Re-probe interval after an account hits a limit. Most limits are SHORT (rolling 5-hour / session /
# rate), not the weekly cap, so we re-try Claude every 20 min and use cheap models in the gap — this
# switches back to costless Claude fast the moment a short limit clears, instead of parking it for hours.
# ORCH_-prefixed so it's tunable fleet-wide via fleet_config. Repeat hits back off (see mark_exhausted).
_COOLDOWN_DEFAULT = 20 * 60
_COOLDOWN_MAX_DEFAULT = 6 * 3600

def _cooldown():
    """Read cooldown from env at call time so hot_reload changes take effect."""
    return int(os.environ.get("ORCH_ACCOUNT_COOLDOWN",
               os.environ.get("ACCOUNT_COOLDOWN", str(_COOLDOWN_DEFAULT))))

def _cooldown_max():
    return int(os.environ.get("ORCH_ACCOUNT_COOLDOWN_MAX", str(_COOLDOWN_MAX_DEFAULT)))

# Keep module-level names for any external readers (read-only; write path uses functions)
COOLDOWN = _cooldown()
COOLDOWN_MAX = _cooldown_max()
# Cheap cross-module signal: written when EVERY Claude account is cooling down, self-expiring
# at the earliest cooldown. agentic_coders.pick() reads claude_exhausted() to fail over to the
# subscription second coder (Codex) instead of stalling. No DB call on the hot path.
EXHAUSTED_FLAG = os.path.join(HOME, "claude_exhausted.json")


# Module-level cache for claude_exhausted(); avoids re-checking flag file/DB on every call.
# Keys: t = timestamp of last check, v = cached boolean result.
_EXH_CACHE = {"t": 0.0, "v": False}


def _api_billing_allowed():
    """Return whether an API-type Anthropic account is actually usable.

    Configured API rows must not mask exhausted subscription capacity when the
    purchased-credit guard is off.  In that state ``env_for`` intentionally
    withholds the key, so treating the row as healthy only sends the CLI back
    through the exhausted default login and prevents cross-vendor failover.
    """
    try:
        import subscription_guard
        return bool(subscription_guard.is_api_allowed())
    except Exception:
        return os.environ.get("ORCH_ALLOW_API_BILLING", "false").lower() == "true"


def claude_exhausted():
    """True iff all Claude accounts are currently cooling down (limits hit).
    Fast path: the flag file written by mark_exhausted. Fallback: derive from the live account
    cooldowns (cached ~15s so high-concurrency pick() calls don't hammer the DB). This makes the
    Codex fail-over engage the moment both accounts are cooling, even if the flag wasn't written."""
    try:
        d = json.load(open(EXHAUSTED_FLAG))
        if time.time() < float(d.get("until", 0)):
            return True
    except Exception:
        pass
    now = time.time()
    if now - _EXH_CACHE["t"] < 15:
        return _EXH_CACHE["v"]
    try:
        v = AccountPool().all_exhausted()
    except Exception:
        v = False
    _EXH_CACHE["t"], _EXH_CACHE["v"] = now, v
    return v


class AccountPool:
    # Re-read config/state every 60s so concurrent runners see each other's cooldowns
    # and DB priority changes without restart.
    _RELOAD_INTERVAL = 60

    def __init__(self):
        self.accts = self._load_cfg()
        self.state = self._load_state()
        self._cfg_ts = time.time()
        self._state_ts = time.time()

    def _maybe_reload(self):
        """Refresh config and state from DB/disk if stale."""
        now = time.time()
        if now - self._cfg_ts > self._RELOAD_INTERVAL:
            self.accts = self._load_cfg()
            self._cfg_ts = now
        if now - self._state_ts > self._RELOAD_INTERVAL:
            self.state = self._load_state()
            self._state_ts = now

    def _load_cfg(self):
        """Load account configuration from Supabase (primary) or local JSON (fallback).

        Accounts are ordered by priority for failover. Machine-affinity filtering
        ensures each Mac only uses accounts assigned to it (or unassigned global ones)."""
        # 1) Supabase `accounts` table is the source of truth (visible in dashboard,
        #    survives restarts, set by Cowork). Ordered by priority asc = failover order.
        try:
            import db, socket
            host = socket.gethostname()
            rows = db.select("accounts", {"select": "*", "order": "priority.asc"})
            if rows:
                # machine affinity: an account with machine=NULL is usable by ANY Mac; one pinned to a
                # hostname is only used on that machine. Prefix-match (host in machine) so that
                # "Mac.lan-scheduler-lane" matches hostname "Mac.lan". Fallback: if ALL affinity-
                # matched accounts are cooling, include ANY healthy unmatched account so lanes
                # never idle when capacity exists somewhere.
                def _affinity(r):
                    m = r.get("machine") or ""
                    return not m or m == host or m.startswith(host) or host in m
                usable = [r for r in rows if _affinity(r)]
                accts = [{"name": r["name"], "type": r.get("type") or "login",
                         "config_dir": r.get("config_dir"),
                         "api_key_env": r.get("api_key_env"), "machine": r.get("machine")}
                        for r in usable]
                # Fallback: if no affinity match OR all matched are cooling, add ALL accounts
                # so the runner can use any healthy one instead of idling.
                if not accts:
                    accts = [{"name": r["name"], "type": r.get("type") or "login",
                              "config_dir": r.get("config_dir"),
                              "api_key_env": r.get("api_key_env"), "machine": r.get("machine")}
                             for r in rows]
                return accts or [{"name": "default", "type": "login"}]
        except Exception:
            pass
        # 2) local file fallback
        if os.path.exists(CFG):
            try: return json.load(open(CFG))
            except Exception: pass
        # 3) default: single implicit account = whatever `claude` already uses
        return [{"name": "default", "type": "login"}]

    def _load_state(self):
        if os.path.exists(STATE):
            try: return json.load(open(STATE))
            except Exception: pass
        return {}

    def _save(self):
        json.dump(self.state, open(STATE, "w"))

    def _healthy(self, a):
        until = self.state.get(a["name"], {}).get("cooldown_until", 0)
        return time.time() >= until

    def _usable_accounts(self):
        """Accounts that can provide Claude capacity under the billing guard."""
        api_allowed = _api_billing_allowed()
        return [a for a in self.accts if a.get("type") != "api" or api_allowed]

    def subscription_accounts(self):
        self._maybe_reload()
        return [a for a in self.accts if a.get("type") != "api"]

    def subscriptions_exhausted(self):
        accounts = self.subscription_accounts()
        return bool(accounts) and not any(self._healthy(a) for a in accounts)

    def current(self):
        self._maybe_reload()
        usable = self._usable_accounts()
        healthy = [a for a in usable if self._healthy(a)]
        if not healthy:
            # all cooling down -> return the one that frees up soonest
            return min(usable,
                       key=lambda a: self.state.get(a["name"], {}).get("cooldown_until", 0)) if usable else None
        # Subscription (Max plan) accounts ALWAYS go before API accounts. Never touch
        # paid API credits while any subscription account still has free capacity.
        subs = [a for a in healthy if a.get("type") != "api"]
        pool = subs if subs else healthy
        # Round-robin across the pool by picking the one with the fewest uses tracked
        # locally. This distributes load evenly across Max plans so one account doesn't
        # burn through its bundled credits while others sit idle.
        if len(pool) > 1:
            return min(pool,
                       key=lambda a: self.state.get(a["name"], {}).get("use_count", 0))
        return pool[0]

    def record_use(self, a):
        """Call after successfully dispatching a task to this account."""
        if not a:
            return
        st = self.state.setdefault(a["name"], {})
        st["use_count"] = int(st.get("use_count", 0)) + 1
        self._save()

    def stats(self):
        """Return a summary dict for observability: total accounts, healthy count,
        exhausted count, per-account cooldown state, and use counts."""
        self._maybe_reload()
        now = time.time()
        entries = []
        for a in self.accts:
            st = self.state.get(a["name"], {})
            cd_until = st.get("cooldown_until", 0)
            entries.append({
                "name": a["name"],
                "type": a.get("type", "login"),
                "healthy": now >= cd_until,
                "cooldown_remaining_s": max(0, int(cd_until - now)),
                "use_count": int(st.get("use_count", 0)),
                "exh_hits": int(st.get("exh_hits", 0)),
            })
        healthy_count = sum(1 for e in entries if e["healthy"])
        return {
            "total": len(entries),
            "healthy": healthy_count,
            "exhausted": len(entries) - healthy_count,
            "accounts": entries,
        }

    def all_exhausted(self):
        """True iff no Claude account is currently healthy (every one is cooling down)."""
        usable = self._usable_accounts()
        return bool(usable) and not any(self._healthy(a) for a in usable)

    def _write_exhausted_flag(self):
        """Persist/clear the cheap cross-module 'all Claude exhausted' signal."""
        try:
            if self.all_exhausted():
                # Use the same billing-guard-filtered set as all_exhausted(). A
                # disabled API row may have an old/expired cooldown and must not
                # make this signal expire while subscriptions are still capped.
                usable = self._usable_accounts()
                soonest = min(self.state.get(a["name"], {}).get("cooldown_until", 0) for a in usable)
                json.dump({"until": soonest}, open(EXHAUSTED_FLAG, "w"))
            elif os.path.exists(EXHAUSTED_FLAG):
                os.remove(EXHAUSTED_FLAG)
        except Exception:
            pass

    def env_for(self, a):
        env = {}
        if not a:
            return env
        if a.get("type") == "api":
            # BILLING GUARD: an api-type account injects ANTHROPIC_API_KEY -> bills prepaid credits,
            # bypassing your Max plan. Refuse unless API billing is explicitly opted in.
            try:
                import subscription_guard
                if not subscription_guard.is_api_allowed():
                    return env  # no key injected -> falls back to subscription login
            except Exception:
                if os.environ.get("ORCH_ALLOW_API_BILLING", "false").lower() != "true":
                    return env
            key = os.environ.get(a.get("api_key_env", "ANTHROPIC_API_KEY"), "")
            if key:
                env["ANTHROPIC_API_KEY"] = key
                env["ORCH_ANTHROPIC_API_ACCOUNT"] = "1"
        elif a.get("config_dir"):
            env["CLAUDE_CONFIG_DIR"] = os.path.expanduser(a["config_dir"])
        return env

    def mark_exhausted(self, a):
        if not a:
            return
        # Exponential backoff: a SHORT limit (session/5-hour/rate) clears on the next 20-min re-probe and
        # mark_ok resets the counter; a PERSISTENT limit (weekly) keeps hitting, so we back off toward
        # COOLDOWN_MAX. This tells short vs long limits apart automatically without parsing messages.
        st = self.state.setdefault(a["name"], {})
        hits = int(st.get("exh_hits", 0)) + 1
        st["exh_hits"] = hits
        st["cooldown_until"] = time.time() + min(_cooldown() * (2 ** (hits - 1)), _cooldown_max())
        self._save()
        self._write_exhausted_flag()   # flip the fail-over-to-Codex signal if this was the last one
        # best-effort: persist cooldown to Supabase so the dashboard shows the rotation
        try:
            import db, datetime
            until = (datetime.datetime.utcnow() +
                     datetime.timedelta(seconds=COOLDOWN)).isoformat()
            db.update("accounts", {"name": a["name"]}, {"cooldown_until": until})
        except Exception:
            pass
        nxt = self.current()
        # notify on rotation / full exhaustion so you stop babysitting
        try:
            import notify
            if nxt and nxt != a["name"]:
                notify.send(f"Account '{a['name']}' hit its limit -> rotated to '{nxt}'.")
            elif not nxt or nxt == a["name"]:
                notify.send(f"ALL accounts exhausted ('{a['name']}' was last). "
                            f"Work pauses until reset or you add capacity.")
        except Exception:
            pass
        return nxt["name"] if nxt else None

    def mark_ok(self, a):
        if a and a["name"] in self.state:
            self.state[a["name"]].pop("cooldown_until", None)
            self.state[a["name"]].pop("exh_hits", None)   # genuine success -> reset the backoff counter
            # Don't reset use_count on mark_ok — it tracks cumulative usage for round-robin
            # balancing. It only resets when ALL accounts' counts are rebalanced (see current()).
            self._save()
            self._write_exhausted_flag()   # a Claude account recovered -> clear the fail-over signal


    def stats(self):
        """Return a dict summarizing pool health for diagnostics and monitoring."""
        self._maybe_reload()
        now = time.time()
        entries = []
        for a in self.accts:
            s = self.state.get(a["name"], {})
            cd = float(s.get("cooldown_until", 0))
            entries.append({
                "name": a["name"],
                "type": a.get("type", "login"),
                "cooling": now < cd,
                "cooldown_remaining_s": max(0, int(cd - now)) if now < cd else 0,
                "use_count": s.get("use_count", 0),
                "exh_hits": s.get("exh_hits", 0),
            })
        return {
            "total": len(entries),
            "healthy": sum(1 for e in entries if not e["cooling"]),
            "cooling": sum(1 for e in entries if e["cooling"]),
            "all_exhausted": self.all_exhausted(),
            "accounts": entries,
        }


if __name__ == "__main__":
    p = AccountPool()
    cur = p.current()
    print("accounts:", [a["name"] for a in p.accts])
    print("current:", cur["name"] if cur else None, "env:", p.env_for(cur))
    print("stats:", json.dumps(p.stats(), indent=2))
