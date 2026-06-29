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


class AccountPool:
    def __init__(self):
        self.accts = self._load_cfg()
        self.state = self._load_state()

    def _load_cfg(self):
        if os.path.exists(CFG):
            try: return json.load(open(CFG))
            except Exception: pass
        # default: single implicit account = whatever `claude` already uses
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

    def env_for(self, a):
        env = {}
        if not a:
            return env
        if a.get("type") == "api":
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
        nxt = self.current()
        return nxt["name"] if nxt else None

    def mark_ok(self, a):
        if a and a["name"] in self.state:
            self.state[a["name"]].pop("cooldown_until", None)
            self._save()


if __name__ == "__main__":
    p = AccountPool()
    cur = p.current()
    print("accounts:", [a["name"] for a in p.accts])
    print("current:", cur["name"] if cur else None, "env:", p.env_for(cur))
