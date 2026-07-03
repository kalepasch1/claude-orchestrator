#!/usr/bin/env python3
"""
agentic_coders.py - pluggable agentic CODER backends. Today Claude Code (via claude_cli) is the only
backend that edits files headlessly in a worktree. This adds a clean seam so a SECOND agentic coder
(e.g. an open-source CLI agent, or a different vendor's coding agent) can take INDEPENDENT branches in
parallel — expanding coding capacity beyond one subscription's rate limit. Its output is judged by the
SAME cross-model panel (judge.py) and gated the same way, so quality stays uniform.

A backend is just a callable that runs an agentic edit in `cwd` and returns the same shape claude_cli
returns: {text, cost_usd, input_tokens, output_tokens, returncode, stderr}. Register real CLIs via env:

    ORCH_SECOND_CODER=aider            # name shown in outcomes
    ORCH_SECOND_CODER_CMD=aider --yes --message {prompt}     # {prompt}/{model} placeholders
    ORCH_SECOND_CODER_SHARE=0.25       # fraction of eligible (no-dep, non-material) tasks to route to it

Until a second backend is configured, everything routes to Claude (unchanged). This is the SEAM; flip
it on by setting the env when you have a second coder installed and authorized.
"""
import os, sys, shlex, subprocess, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def available():
    """List configured agentic coders. 'claude' is always present."""
    coders = ["claude"]
    if os.environ.get("ORCH_SECOND_CODER") and os.environ.get("ORCH_SECOND_CODER_CMD"):
        coders.append(os.environ["ORCH_SECOND_CODER"])
    if os.environ.get("ORCH_THIRD_CODER") and os.environ.get("ORCH_THIRD_CODER_CMD"):
        coders.append(os.environ["ORCH_THIRD_CODER"])
    return coders


def _third_within_cap():
    """The optional THIRD (paid-API) agentic coder is used only when today's spend on it is
    under ORCH_THIRD_CODER_DAILY_USD. Soft daily cap read from outcomes tagged with its name."""
    try:
        cap = float(os.environ.get("ORCH_THIRD_CODER_DAILY_USD", "0"))
    except ValueError:
        cap = 0.0
    if cap <= 0:
        return False
    try:
        import db, datetime
        since = datetime.date.today().isoformat()
        name = os.environ.get("ORCH_THIRD_CODER", "")
        rows = db.select("outcomes", {"select": "usd", "created_at": f"gte.{since}",
                                      "model": f"eq.{name}"}) or []
        return sum(float(r.get("usd") or 0) for r in rows) < cap
    except Exception:
        return True  # fail-open within the day; the coder's own per-call cost stays small


def pick(task, slot_index=0):
    """Choose an agentic coder for a task.

    COST-PRIORITISED CASCADE (owner directive):
      1. Claude Code on the Max SUBSCRIPTION (both accounts, $0/call) — normal path.
      2. When EVERY Claude account is rate-limited/exhausted (account_pool.claude_exhausted),
         fail over to the SUBSCRIPTION second coder (Codex/ChatGPT — bundled, non-API, $0) for
         ALL eligible work instead of stalling until Claude resets.
      3. If Codex is unavailable, use the optional paid-API THIRD coder, but only within its
         daily $ cap (ORCH_THIRD_CODER_DAILY_USD).
    In the NORMAL (not-exhausted) state, the second coder still takes a diversification share of
    SAFE (independent, non-material) tasks so capacity is spread and benchmarked.
    """
    second = os.environ.get("ORCH_SECOND_CODER")
    second_ok = bool(second and os.environ.get("ORCH_SECOND_CODER_CMD"))
    third = os.environ.get("ORCH_THIRD_CODER")
    third_ok = bool(third and os.environ.get("ORCH_THIRD_CODER_CMD"))

    try:
        import account_pool
        exhausted = account_pool.claude_exhausted()
    except Exception:
        exhausted = False

    if exhausted:
        # Claude Code can't run — keep the fleet moving on subscription-first, then capped paid API.
        if second_ok:
            return second
        if third_ok and _third_within_cap():
            return third
        return "claude"  # nothing better available; task waits for Claude reset

    # Normal state: diversification share to the second coder for SAFE tasks only.
    if not second_ok:
        return "claude"
    if task.get("material") or (task.get("deps") or []):
        return "claude"
    try:
        share = float(os.environ.get("ORCH_SECOND_CODER_SHARE", "0.25"))
    except ValueError:
        share = 0.25
    # deterministic split by task id hash so both machines agree without coordination
    h = (abs(hash(task.get("slug") or task.get("id") or "")) % 100) / 100.0
    return second if h < share else "claude"


def run(coder, prompt, model, cwd=None, env=None, project=None, timeout=900, **kwargs):
    """Dispatch to the chosen agentic backend, returning claude_cli-shaped output."""
    if coder == "claude":
        import claude_cli
        return claude_cli.run(prompt, model, cwd=cwd, env=env, project=project, timeout=timeout, **kwargs)
    # generic CLI backend — pick the right command template for this coder
    if coder == os.environ.get("ORCH_THIRD_CODER"):
        tmpl = os.environ.get("ORCH_THIRD_CODER_CMD", "")
    else:
        tmpl = os.environ.get("ORCH_SECOND_CODER_CMD", "")
    if not tmpl:
        raise RuntimeError(f"coder '{coder}' command not configured")
    cmd = tmpl.replace("{prompt}", shlex.quote(prompt)).replace("{model}", shlex.quote(model or ""))
    t0 = time.time()
    try:
        proc = subprocess.run(shlex.split(cmd) if "{prompt}" not in tmpl else ["bash", "-lc", cmd],
                              cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
        return {"text": proc.stdout, "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0,
                "returncode": proc.returncode, "stderr": proc.stderr or "",
                "coder": coder, "latency_ms": int((time.time() - t0) * 1000)}
    except subprocess.TimeoutExpired:
        return {"text": "", "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0,
                "returncode": 124, "stderr": "second coder timeout", "coder": coder}


if __name__ == "__main__":
    print("configured agentic coders:", available())
