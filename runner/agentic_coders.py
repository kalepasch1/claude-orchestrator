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
    return coders


def pick(task, slot_index=0):
    """Choose a coder for a task. Only route to a second coder when it's SAFE: independent
    (no deps), non-material, and within the configured share. Otherwise Claude."""
    second = os.environ.get("ORCH_SECOND_CODER")
    if not second or not os.environ.get("ORCH_SECOND_CODER_CMD"):
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


def run(coder, prompt, model, cwd=None, env=None, project=None, timeout=900):
    """Dispatch to the chosen agentic backend, returning claude_cli-shaped output."""
    if coder == "claude":
        import claude_cli
        return claude_cli.run(prompt, model, cwd=cwd, env=env, project=project, timeout=timeout)
    # generic CLI backend
    tmpl = os.environ.get("ORCH_SECOND_CODER_CMD", "")
    if not tmpl:
        raise RuntimeError("second coder command not configured")
    cmd = tmpl.replace("{prompt}", prompt).replace("{model}", model or "")
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
