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
STATE = os.path.join(HOME, "accounts_state.json")
COOLDOWN = int(os.environ.get("ACCOUNT_COOLDOWN", str(4 * 3600)))
# Cheap cross-module signal: written when EVERY Claude account is cooling down, self-expiring
# at the earliest cooldown. agentic_coders.pick() reads claude_exhausted() to fail over to the
# subscription second coder (Codex) instead of stalling. No DB call on the hot path.
EXHAUSTED_FLAG = os.path.join(HOME, "claude_exhausted.json")


_EXH_CACHE = {"t": 0.0, "v": False}


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
    def __init__(self):
        self.accts = self._load_cfg()
        self.state = self._load_state()

    def _load_cfg(self):
        # 1) Supabase `accounts` table is the source of truth (visible in dashboard,
        #    survives restarts, set by Cowork). Ordered by priority asc = failover order.
        try:
            import db, socket
            host = socket.gethostname()
            rows = db.select("accounts", {"select": "*", "order": "priority.asc"})
            if rows:
                # machine affinity: an account with machine=NULL is usable by ANY Mac; one pinned to a
                # hostname is only used on that machine. Lets you add a 2nd seat later and pin seat->Mac
                # so the two runners don't contend on one login. Today (shared) = leave machine NULL.
                usable = [r for r in rows if not r.get("machine") or r.get("machine") == host]
                return [{"name": r["name"], "type": r.get("type") or "login",
                         "config_dir": r.get("config_dir"),
                         "api_key_env": r.get("api_key_env"), "machine": r.get("machine")}
                        for r in usable] or [{"name": "default", "type": "login"}]
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

    def current(self):
        for a in self.accts:
            if self._healthy(a):
                return a
        # all cooling down -> return the one that frees up soonest
        return min(self.accts,
                   key=lambda a: self.state.get(a["name"], {}).get("cooldown_until", 0)) if self.accts else None

    def all_exhausted(self):
        """True iff no Claude account is currently healthy (every one is cooling down)."""
        return bool(self.accts) and not any(self._healthy(a) for a in self.accts)

    def _write_exhausted_flag(self):
        """Persist/clear the cheap cross-module 'all Claude exhausted' signal."""
        try:
            if self.all_exhausted():
                soonest = min(self.state.get(a["name"], {}).get("cooldown_until", 0) for a in self.accts)
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
        elif a.get("config_dir"):
            env["CLAUDE_CONFIG_DIR"] = os.path.expanduser(a["config_dir"])
        return env

    def mark_exhausted(self, a):
        if not a:
            return
        self.state.setdefault(a["name"], {})["cooldown_until"] = time.time() + COOLDOWN
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
            self._save()
            self._write_exhausted_flag()   # a Claude account recovered -> clear the fail-over signal


if __name__ == "__main__":
    p = AccountPool()
    cur = p.current()
    print("accounts:", [a["name"] for a in p.accts])
    print("current:", cur["name"] if cur else None, "env:", p.env_for(cur))
