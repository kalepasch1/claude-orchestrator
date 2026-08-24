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
  4. AGENT SDK PATH: when ORCH_USE_SDK=true, uses the claude-agent-sdk Python package for
     structured output, rate limit events, and per-task budget caps. Still uses subscription
     tokens (not API billing) — the SDK wraps the CLI with the same OAuth auth.

Usage (replace every `subprocess.run([CLAUDE_BIN,'-p',...,'--output-format','text'])`):
    from claude_cli import run
    r = run(prompt, model, cwd=..., env=..., project="tomorrow")
    text = r["text"]; cost = r["cost_usd"]; rc = r["returncode"]
"""
import os, sys, json, time, subprocess, threading, logging, asyncio
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

log = logging.getLogger(__name__)

# --- Agent SDK availability probe (runs once at import) ---
_HAS_AGENT_SDK = False
try:
    from claude_agent_sdk import query as _sdk_query, ClaudeAgentOptions, AssistantMessage, TextBlock, ResultMessage
    _HAS_AGENT_SDK = True
except ImportError:
    _sdk_query = ClaudeAgentOptions = AssistantMessage = TextBlock = ResultMessage = None

CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
STATE = os.path.join(HOME, "call_budget.json")
# Safe-by-default caps: even if .env is missing these, a bug cannot exceed them.
# Override upward in runner/.env only if you deliberately want more headroom.
MAX_CALLS_HOUR = int(os.environ.get("CLAUDE_MAX_CALLS_PER_HOUR", "80"))
MAX_USD_HOUR = float(os.environ.get("CLAUDE_MAX_USD_PER_HOUR", "10"))
MAX_USD_DAY = float(os.environ.get("CLAUDE_MAX_USD_PER_DAY", "40"))
# THROUGHPUT FIX 2026-08-02: the *cost* breakers were made subscription-aware (see _record:
# "sub_usd ... never trips caps") but the *call-count* breaker was not — so every free
# subscription call burned the same 80/hr budget as a billable API call. With ~2,200 tasks
# queued the fleet was pinned at ~60 model calls/hour (1/min) purely by this counter, with
# zero worker processes running most of the time. Billable calls stay capped at
# MAX_CALLS_HOUR (that protects the wallet); subscription calls get their own, much higher
# ceiling whose only job is to stop a runaway loop, not to pace normal work.
MAX_SUB_CALLS_HOUR = int(os.environ.get("CLAUDE_MAX_SUB_CALLS_PER_HOUR", "600"))
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


def _billable_calls(calls):
    """Count only calls that cost real money.

    Entry shape is [ts, 1, billable] where billable is 1/0. Entries written before this
    field existed are 2-element and are treated as NON-billable: real spend is tracked
    independently in `spend`, so a legacy entry can never hide a dollar, and treating them
    as billable would instantly trip the breaker on upgrade.
    """
    return sum(1 for x in calls if len(x) > 2 and x[2])


def _check_budget():
    s = _load()
    calls = _within(s.get("calls", []), 3600)
    hour_usd = sum(x[1] for x in _within(s.get("spend", []), 3600))
    day_usd = sum(x[1] for x in _within(s.get("spend", []), 86400))
    billable = _billable_calls(calls)
    if billable >= MAX_CALLS_HOUR:
        raise CircuitOpen(f"billable call cap: {billable}/{MAX_CALLS_HOUR} per hour")
    if len(calls) >= MAX_SUB_CALLS_HOUR:
        raise CircuitOpen(
            f"total call cap: {len(calls)}/{MAX_SUB_CALLS_HOUR} per hour (runaway guard)")
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
        # 3rd element = billable flag, so the call breaker can tell a free subscription
        # call apart from one that costs real money (see MAX_SUB_CALLS_HOUR).
        s["calls"] = _within(s.get("calls", []), 86400) + [[now, 1, 1 if float(usd or 0) > 0 else 0]]
        s["spend"] = _within(s.get("spend", []), 86400) + [[now, float(usd or 0)]]
        s["sub_spend"] = _within(s.get("sub_spend", []), 86400) + [[now, float(sub_usd or 0)]]
        _save(s)


def _paused(project=None):
    try:
        import kill_switch
        return kill_switch.is_paused(project)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Terminal-reason detection
#
# The CLI/SDK signal a turn-budget exhaustion as
#   {"type":"result","subtype":"error_max_turns","is_error":true,...}
# which carries no "result" key. Before this, run() fell through to the raw-stdout
# fallback and returned a normal-looking payload, so callers (approval digest
# batching among them) could not distinguish "agent finished" from "agent ran out
# of turns mid-edit" and retried forever. Every run() result now carries an
# explicit `terminal_reason` plus a human-readable `error`.
# ---------------------------------------------------------------------------

TERMINAL_MAX_TURNS = "max_turns"

_MAX_TURNS_TEXT_MARKERS = (
    "reached maximum number of turns",
    "error_max_turns",
    "max turns exceeded",
)


def detect_terminal_reason(raw=None, text="", stderr=""):
    """Classify how a Claude run ended. Pure — no I/O, safe to call anywhere.

    Returns (terminal_reason, error_detail). `terminal_reason` is None for a normal
    completion. Fail-soft: any unexpected shape yields (None, None) rather than raising.
    """
    try:
        detail = None
        subtype = stop = None
        if isinstance(raw, dict):
            subtype = str(raw.get("subtype") or "")
            stop = str(raw.get("stop_reason") or "")
            for key in ("error", "error_message", "message"):
                val = raw.get(key)
                if isinstance(val, str) and val:
                    detail = val
                    break
        blob = " ".join(
            str(p) for p in (subtype, stop, detail, text, stderr) if p
        ).lower()
        if subtype == "error_max_turns" or stop == TERMINAL_MAX_TURNS or any(
            m in blob for m in _MAX_TURNS_TEXT_MARKERS
        ):
            turns = raw.get("num_turns") if isinstance(raw, dict) else None
            suffix = f" after {turns} turn(s)" if turns else ""
            return TERMINAL_MAX_TURNS, detail or (
                f"Reached maximum number of turns{suffix}"
            )
        if isinstance(raw, dict) and raw.get("is_error"):
            return "error", detail or "run reported is_error"
        return None, None
    except Exception:
        return None, None


def succeeded(result):
    """True when `result` represents a run that actually finished its work.

    Callers previously read `result["text"]` and treated anything non-empty as a
    completion, so a max_turns stop looked identical to success. This is the one place
    that question is answered. Fail-soft and tolerant of legacy dicts that predate
    `terminal_reason`: a plain {"returncode": 0} still reads as success, and a
    non-dict reads as failure rather than raising.
    """
    if not isinstance(result, dict):
        return False
    if result.get("terminal_reason"):
        return False
    try:
        return int(result.get("returncode") or 0) == 0
    except (TypeError, ValueError):
        return False


def failure_reason(result):
    """Short human-readable reason a run did not succeed, or None if it did.

    Never raises, and never returns an empty string — an empty reason next to a
    failed run is exactly the silent case this exists to remove.
    """
    if succeeded(result):
        return None
    if not isinstance(result, dict):
        return "no result object returned"
    reason = result.get("terminal_reason")
    detail = result.get("error") or result.get("stderr") or ""
    detail = " ".join(str(detail).split())[:200]
    if reason == TERMINAL_MAX_TURNS:
        return f"max_turns: {detail or 'reached maximum number of turns'}"
    if reason:
        return f"{reason}: {detail}" if detail else str(reason)
    if result.get("skipped"):
        return f"skipped: {result['skipped']}"
    return detail or f"exited {result.get('returncode')}"


# ---------------------------------------------------------------------------
# Agent SDK path — uses subscription tokens via the CLI's OAuth auth.
# Same billing as the CLI subprocess path, but with structured output,
# rate limit events, and per-task budget caps.
# ---------------------------------------------------------------------------

async def _run_agent_sdk_async(prompt, model, cwd, runenv, project, max_turns, timeout):
    """Execute a Claude call via the claude-agent-sdk Python package.

    Uses the same CLI binary and subscription auth as the subprocess path.
    Returns the same dict format: {text, cost_usd, input_tokens, output_tokens,
    returncode, raw, stderr}.
    """
    # Map permission mode: bypassPermissions = dangerously-skip-permissions equivalent
    perm_mode = "bypassPermissions"
    if os.environ.get("ORCH_SKIP_PERMISSIONS", "true").lower() != "true":
        perm_mode = "acceptEdits"

    # Build env dict for the SDK — only pass overrides, not the full env
    # (the SDK inherits the current process env and merges these on top).
    sdk_env = {}
    # Pass through account-specific config dir if set (for account rotation)
    for key in ("CLAUDE_CONFIG_DIR", "ANTHROPIC_API_KEY", "ORCH_ANTHROPIC_API_ACCOUNT"):
        val = runenv.get(key)
        if val:
            sdk_env[key] = val

    options = ClaudeAgentOptions(
        model=model,
        max_turns=max_turns or 60,
        cwd=str(cwd) if cwd else None,
        permission_mode=perm_mode,
        cli_path=CLAUDE_BIN,
        env=sdk_env,
    )

    collected_text = []
    cost = 0.0
    itok = 0
    otok = 0
    num_turns = 0
    returncode = 0
    rate_limit_type = None
    result_subtype = ""

    async for message in _sdk_query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    collected_text.append(block.text)
        elif isinstance(message, ResultMessage):
            cost = message.total_cost_usd or 0.0
            usage = message.usage or {}
            itok = usage.get("input_tokens", 0)
            otok = usage.get("output_tokens", 0)
            num_turns = message.num_turns or 0
            result_subtype = str(getattr(message, "subtype", "") or "")
            if message.result:
                collected_text = [message.result]
            if message.is_error:
                returncode = 1
        else:
            # Check for rate limit events (for account rotation signaling)
            msg_type = getattr(message, "type", None)
            if msg_type == "rate_limit":
                rate_limit_type = getattr(message, "rate_limit_type", None)
                log.warning("Rate limit hit: %s", rate_limit_type)

    text = "\n".join(collected_text) if collected_text else ""

    raw = {"result": text, "total_cost_usd": cost,
           "usage": {"input_tokens": itok, "output_tokens": otok},
           "agent_sdk": True, "turns": num_turns,
           "num_turns": num_turns, "subtype": result_subtype,
           "is_error": bool(returncode)}
    terminal_reason, error_detail = detect_terminal_reason(raw, text, "")
    if terminal_reason == TERMINAL_MAX_TURNS:
        returncode = returncode or 1

    return {
        "text": text,
        "cost_usd": cost,
        "input_tokens": itok,
        "output_tokens": otok,
        "returncode": returncode,
        "raw": raw,
        "stderr": "",
        "rate_limit_type": rate_limit_type,
        "terminal_reason": terminal_reason,
        "error": error_detail,
    }


def _run_agent_sdk(prompt, model, cwd, runenv, project, max_turns, timeout):
    """Synchronous wrapper — safe to call from the runner's daemon threads."""
    # WEDGEFIX-A-SDK-TIMEOUT
    loop = asyncio.new_event_loop()
    try:
        _coro = _run_agent_sdk_async(prompt, model, cwd, runenv, project, max_turns, timeout)
        if timeout:
            _coro = asyncio.wait_for(_coro, timeout=timeout)
        return loop.run_until_complete(_coro)
    except asyncio.TimeoutError:
        raise subprocess.TimeoutExpired(cmd="claude-agent-sdk", timeout=timeout)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------

def run(prompt, model, cwd=None, env=None, project=None, max_turns=60,
        permission="acceptEdits", timeout=None, output_only=True):
    """Metered Claude call. Returns {text, cost_usd, input_tokens, output_tokens, returncode, raw}."""
    if _paused(project):
        return {"text": "", "cost_usd": 0, "input_tokens": 0, "output_tokens": 0,
                "returncode": 75, "raw": None, "skipped": "kill_switch"}
    with _lock:
        _check_budget()          # raises CircuitOpen if over cap

    # --- Route: Agent SDK vs CLI subprocess ---
    # Both paths use subscription tokens (not API billing). The SDK path gives us
    # structured output, rate limit events, and per-task budget caps.
    use_sdk = (os.environ.get("ORCH_USE_SDK", "false").lower() == "true"
               and _HAS_AGENT_SDK)

    # Build the subprocess environment. Strip API key to stay on subscription billing
    # unless an explicit API account was selected AND billing is allowed.
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

    # --- Agent SDK path (subscription tokens, structured output) ---
    if use_sdk:
        try:
            result = _run_agent_sdk(prompt, model, cwd, runenv, project, max_turns, timeout)
            cost = result["cost_usd"]
            # SDK uses subscription — real billable cost is 0 unless on API account
            real_usd = cost if using_api else 0.0
            _record(real_usd, sub_usd=cost)
            try:
                import usage_meter
                itok, otok = result["input_tokens"], result["output_tokens"]
                usage_meter.record("anthropic", project, units=itok + otok, unit="tokens", usd=real_usd)
                if not using_api and cost:
                    usage_meter.record("anthropic-notional", project, units=itok + otok,
                                       unit="tokens", usd=cost)
            except Exception:
                pass
            # Signal rate limits to account_pool for rotation AND subscription_tracker
            if result.get("rate_limit_type"):
                try:
                    import account_pool
                    account_pool.pool.mark_exhausted(
                        reason=f"sdk_rate_limit:{result['rate_limit_type']}")
                except Exception:
                    pass
                try:
                    import subscription_tracker
                    subscription_tracker.record_call("claude-max", "rate_limited", model)
                except Exception:
                    pass
            else:
                try:
                    import subscription_tracker
                    subscription_tracker.record_call("claude-max", "success", model)
                except Exception:
                    pass
            return result
        except Exception as exc:
            log.warning("Agent SDK path failed (%s); falling back to CLI subprocess", exc)
            # Fall through to CLI path below

    # --- API-direct path: bypass CLI/subscription, call Anthropic Messages API ---
    # Activated when ORCH_EXEC_MODE=api|hybrid AND subscription is exhausted.
    # Uses the swarm executor for direct HTTP calls — no rate limits, pay-per-use.
    if os.environ.get("ORCH_EXEC_MODE", "cli").lower() in ("api", "hybrid", "swarm"):
        try:
            from account_pool import claude_exhausted
            if claude_exhausted():
                import swarm_executor
                log.info("Subscription exhausted — routing to API-direct via swarm_executor")
                result = swarm_executor.run_swarm(prompt, model, provider="claude",
                                                  cwd=cwd, timeout=timeout or 900, mode="agentic")
                real_usd = result.get("cost_usd", 0)
                _record(real_usd)
                try:
                    import usage_meter
                    usage_meter.record("anthropic-api", project,
                                       units=result.get("input_tokens", 0) + result.get("output_tokens", 0),
                                       unit="tokens", usd=real_usd)
                except Exception:
                    pass
                return result
        except ImportError:
            pass
        except Exception as exc:
            log.warning("API-direct path failed (%s); falling back to CLI subprocess", exc)

    # --- CLI subprocess path (original) ---
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
    # Track CLI subscription usage for tier routing
    try:
        import subscription_tracker
        _cli_outcome = "success" if proc.returncode == 0 else "fail"
        # Detect rate limit signals in stderr (CLI emits "usage limit" or "rate limit" on exhaustion)
        if proc.stderr and ("usage limit" in proc.stderr.lower() or "rate limit" in proc.stderr.lower()):
            _cli_outcome = "rate_limited"
        subscription_tracker.record_call("claude-max", _cli_outcome, model)
    except Exception:
        pass
    # Turn-budget exhaustion is a FAILURE, not a completion — surface it by name so
    # callers stop treating a half-finished edit as a delivered result.
    terminal_reason, error_detail = detect_terminal_reason(raw, text, proc.stderr or "")
    returncode = proc.returncode
    if terminal_reason == TERMINAL_MAX_TURNS:
        log.warning("claude run hit max_turns: %s", error_detail)
        returncode = returncode or 1
    return {"text": text, "cost_usd": cost, "input_tokens": itok, "output_tokens": otok,
            "returncode": returncode, "raw": raw, "stderr": proc.stderr or "",
            "terminal_reason": terminal_reason, "error": error_detail}


def status():
    s = _load()
    hour_calls = _within(s.get("calls", []), 3600)
    return {"calls_last_hour": len(hour_calls),
            "billable_calls_last_hour": _billable_calls(hour_calls),
            "usd_last_hour": round(sum(x[1] for x in _within(s.get("spend", []), 3600)), 2),
            "usd_last_day": round(sum(x[1] for x in _within(s.get("spend", []), 86400)), 2),
            "sub_equiv_last_hour": round(sum(x[1] for x in _within(s.get("sub_spend", []), 3600)), 2),
            "sub_equiv_last_day": round(sum(x[1] for x in _within(s.get("sub_spend", []), 86400)), 2),
            "caps": {"billable_calls_hr": MAX_CALLS_HOUR, "total_calls_hr": MAX_SUB_CALLS_HOUR,
                     "usd_hr": MAX_USD_HOUR, "usd_day": MAX_USD_DAY}}


if __name__ == "__main__":
    print(json.dumps(status(), indent=2))
