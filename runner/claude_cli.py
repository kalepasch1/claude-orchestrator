#!/usr/bin/env python3
"""
claude_cli.py - the ONE metered, circuit-broken entrypoint for every Claude call.
Routing all model calls through here is the systemic fix for the ~$400 runaway:

  1. KILL SWITCH: refuses to run if the global/project pause is set — so even scheduled
     subprocess jobs honor the pause WITHOUT restarting the runner.
  2. HOURLY CIRCUIT BREAKER: hard caps on calls/hour and $/hour (across all modules, via a
     shared local counter) — a single bug can no longer make 60k calls.
  3. REAL COST CAPTURE: uses `--output-format json` to read total_cost_usd + usage, records
     it to provider_usage, and returns it — so budgets/anomaly finally SEE spend.

Usage (replace every `subprocess.run([CLAUDE_BIN,'-p',...,'--output-format','text'])`):
    from claude_cli import run
    r = run(prompt, model, cwd=..., env=..., project="tomorrow")
    text = r["text"]; cost = r["cost_usd"]; rc = r["returncode"]
"""
import os, sys, json, time, subprocess, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
STATE = os.path.join(HOME, "call_budget.json")
# Safe-by-default caps: even if .env is missing these, a bug cannot exceed them.
# Override upward in runner/.env only if you deliberately want more headroom.
MAX_CALLS_HOUR = int(os.environ.get("CLAUDE_MAX_CALLS_PER_HOUR", "80"))
MAX_USD_HOUR = float(os.environ.get("CLAUDE_MAX_USD_PER_HOUR", "10"))
MAX_USD_DAY = float(os.environ.get("CLAUDE_MAX_USD_PER_DAY", "40"))
_lock = threading.Lock()
os.makedirs(HOME, exist_ok=True)


class CircuitOpen(RuntimeError):
    pass


def _load():
    try:
        return json.load(open(STATE))
    except Exception:
        return {"calls": [], "spend": []}   # lists of [ts, usd]


def _save(s):
    try:
        json.dump(s, open(STATE, "w"))
    except Exception:
        pass


def _within(items, seconds):
    cut = time.time() - seconds
    return [x for x in items if x[0] >= cut]


def _check_budget():
    s = _load()
    calls = _within(s.get("calls", []), 3600)
    hour_usd = sum(x[1] for x in _within(s.get("spend", []), 3600))
    day_usd = sum(x[1] for x in _within(s.get("spend", []), 86400))
    if len(calls) >= MAX_CALLS_HOUR:
        raise CircuitOpen(f"call cap: {len(calls)}/{MAX_CALLS_HOUR} per hour")
    if hour_usd >= MAX_USD_HOUR:
        raise CircuitOpen(f"hourly $ cap: ${hour_usd:.2f}/${MAX_USD_HOUR}")
    if day_usd >= MAX_USD_DAY:
        raise CircuitOpen(f"daily $ cap: ${day_usd:.2f}/${MAX_USD_DAY}")


def _record(usd, sub_usd=0):
    # `usd` = REAL billable dollars (0 in subscription mode) -> feeds the $ circuit breaker.
    # `sub_usd` = subscription-EQUIVALENT cost -> tracked for visibility only, never trips caps.
    with _lock:
        s = _load()
        now = time.time()
        s["calls"] = _within(s.get("calls", []), 86400) + [[now, 1]]
        s["spend"] = _within(s.get("spend", []), 86400) + [[now, float(usd or 0)]]
        s["sub_spend"] = _within(s.get("sub_spend", []), 86400) + [[now, float(sub_usd or 0)]]
        _save(s)


def _paused(project=None):
    try:
        import kill_switch
        return kill_switch.is_paused(project)
    except Exception:
        return False


def run(prompt, model, cwd=None, env=None, project=None, max_turns=60,
        permission="acceptEdits", timeout=None, output_only=True):
    """Metered Claude call. Returns {text, cost_usd, input_tokens, output_tokens, returncode, raw}."""
    if _paused(project):
        return {"text": "", "cost_usd": 0, "input_tokens": 0, "output_tokens": 0,
                "returncode": 75, "raw": None, "skipped": "kill_switch"}
    with _lock:
        _check_budget()          # raises CircuitOpen if over cap
    cmd = [CLAUDE_BIN, "-p", prompt, "--model", model, "--output-format", "json"]
    # Agents run inside per-task git WORKTREES, which are fresh paths the user never trusted —
    # so Claude Code ignores .claude/settings.local.json ("workspace not trusted") and stalls.
    # For an autonomous runner the correct mode is to skip the interactive trust/permission gate
    # entirely. Guarded by env so it can be turned off. Supersedes --permission-mode.
    if os.environ.get("ORCH_SKIP_PERMISSIONS", "true").lower() == "true":
        cmd += ["--dangerously-skip-permissions"]
    elif permission:
        cmd += ["--permission-mode", permission]
    if max_turns:
        cmd += ["--max-turns", str(max_turns)]
    # Use Max SUBSCRIPTION logins first. A paid API key is kept only when account_pool selected an
    # explicit api account AND subscription_guard says paid fallback is allowed. This prevents a
    # stray process-level ANTHROPIC_API_KEY from silently turning ordinary subscription calls into
    # billable API calls.
    runenv = dict(env if env is not None else os.environ)
    subscription = os.environ.get("ORCH_USE_SUBSCRIPTION", "true").lower() == "true"
    api_account = runenv.get("ORCH_ANTHROPIC_API_ACCOUNT") == "1"
    try:
        import subscription_guard
        api_allowed = subscription_guard.is_api_allowed()
    except Exception:
        api_allowed = os.environ.get("ORCH_ALLOW_API_BILLING", "false").lower() == "true"
    if subscription and not (api_account and api_allowed):
        runenv.pop("ANTHROPIC_API_KEY", None)
        runenv.pop("ORCH_ANTHROPIC_API_ACCOUNT", None)
    using_api = bool(runenv.get("ANTHROPIC_API_KEY"))
    # GLOBAL $200 real-spend ceiling also covers Claude's PAID API. When the ceiling is hit, drop the API
    # key and fall back to the free Max subscription instead of spending more real dollars — work keeps
    # flowing at $0 rather than failing, and real spend stays capped pending approval.
    if using_api:
        try:
            import budget
            if not budget.paid_allowed():
                runenv.pop("ANTHROPIC_API_KEY", None)
                runenv.pop("ORCH_ANTHROPIC_API_ACCOUNT", None)
                using_api = False
        except Exception:
            pass
    proc = subprocess.run(cmd, cwd=cwd, env=runenv, capture_output=True, text=True, timeout=timeout)
    text, cost, itok, otok, raw = proc.stdout, 0.0, 0, 0, None
    try:
        raw = json.loads(proc.stdout)
        # Claude Code JSON envelope: {"result": "...", "total_cost_usd": x, "usage": {...}}
        text = raw.get("result", proc.stdout)
        cost = float(raw.get("total_cost_usd", 0) or 0)
        usage = raw.get("usage", {}) or {}
        itok = int(usage.get("input_tokens", 0) or 0)
        otok = int(usage.get("output_tokens", 0) or 0)
    except Exception:
        text = proc.stdout + proc.stderr      # non-JSON fallback (older CLI)
    # Subscription calls are costless; explicit API fallback is real billable spend and is recorded
    # as such so the billing guard can enforce the daily cap.
    real_usd = cost if using_api else 0.0
    _record(real_usd, sub_usd=cost)
    try:
        import usage_meter
        # Record REAL billable $ under 'anthropic' and subscription-equivalent under
        # 'anthropic-notional' only for fixed-price login usage.
        usage_meter.record("anthropic", project, units=itok + otok, unit="tokens", usd=real_usd)
        if not using_api and cost:
            usage_meter.record("anthropic-notional", project, units=itok + otok, unit="tokens", usd=cost)
    except Exception:
        pass
    # cost_usd is REAL billable dollars (0 on subscription) — this is what flows into outcomes.usd /
    # v_spend_mtd / budgets, so the budget reflects money actually spent, not the notional token price
    # of costless subscription calls (the phantom "$236 spent" that forced the absurd $100k caps).
    # notional_usd keeps the subscription-equivalent for visibility only.
    return {"text": text, "cost_usd": real_usd, "notional_usd": cost,
            "input_tokens": itok, "output_tokens": otok,
            "returncode": proc.returncode, "raw": raw, "stderr": proc.stderr or ""}


def status():
    s = _load()
    return {"calls_last_hour": len(_within(s.get("calls", []), 3600)),
            "usd_last_hour": round(sum(x[1] for x in _within(s.get("spend", []), 3600)), 2),
            "usd_last_day": round(sum(x[1] for x in _within(s.get("spend", []), 86400)), 2),
            "sub_equiv_last_hour": round(sum(x[1] for x in _within(s.get("sub_spend", []), 3600)), 2),
            "sub_equiv_last_day": round(sum(x[1] for x in _within(s.get("sub_spend", []), 86400)), 2),
            "caps": {"calls_hr": MAX_CALLS_HOUR, "usd_hr": MAX_USD_HOUR, "usd_day": MAX_USD_DAY}}


if __name__ == "__main__":
    print(json.dumps(status(), indent=2))
