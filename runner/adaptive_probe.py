#!/usr/bin/env python3
"""Probe-first routing for expensive agentic work.

A small local/cheap model gets a minimized diagnostic prompt first. The coder then
receives a smaller, higher-signal slice instead of the full strategic burden.
"""
from __future__ import annotations

import os
import sys
from typing import Callable, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MARK = "ADAPTIVE PROBE-FIRST SLICE"


# ---------------------------------------------------------------------------
# Probe backend seam.
#
# make_probe used to reach its model through a function-local
# `import model_policy, model_gateway`, which meant the only way to substitute
# a model in a test was to replace the entry in sys.modules. runner/tests/
# conftest.py deliberately RESTORES control-plane modules that a test replaced
# that way, so those substitutions were reverted before the test body ran and
# the "failure" cases quietly called a live provider instead — 24 unit tests
# took 52 seconds and three of them asserted against whatever the model said.
#
# The dependency is now injected rather than discovered. set_probe_backend()
# is the seam; when nothing is injected the real modules are resolved at CALL
# time, so production behaviour is unchanged.
# ---------------------------------------------------------------------------
_COMPLETION: Optional[Callable[..., dict]] = None
_CHOOSER: Optional[Callable[..., Tuple]] = None


def set_probe_backend(complete: Optional[Callable[..., dict]] = None,
                      choose: Optional[Callable[..., Tuple]] = None) -> None:
    """Inject the completion/routing callables the probe should use."""
    global _COMPLETION, _CHOOSER
    if complete is not None:
        _COMPLETION = complete
    if choose is not None:
        _CHOOSER = choose


def reset_probe_backend() -> None:
    """Drop any injected backend and go back to the real modules."""
    global _COMPLETION, _CHOOSER
    _COMPLETION = None
    _CHOOSER = None


def _resolve_backend() -> Tuple[Callable[..., Tuple], Callable[..., dict]]:
    """Resolve (choose, complete), preferring anything injected.

    Resolution happens per call, not at import, so a late injection is honoured
    and an un-injected process still picks up the real gateway.
    """
    choose, complete = _CHOOSER, _COMPLETION
    if choose is None or complete is None:
        import model_policy, model_gateway
        if choose is None:
            choose = model_policy.choose
        if complete is None:
            complete = model_gateway.complete
    return choose, complete


def should_probe(task: Optional[dict], prompt: Optional[str]) -> bool:
    if os.environ.get("ORCH_ADAPTIVE_PROBE", "true").lower() not in ("1", "true", "yes", "on"):
        return False
    if MARK in str(prompt or ""):
        return False
    kind = str((task or {}).get("kind") or "").lower()
    if kind in ("mechanical", "chore", "docs", "cleanup", "canary"):
        return False
    text = str(prompt or "")
    char_threshold = int(os.environ.get("ORCH_ADAPTIVE_PROBE_CHARS", "1200"))
    if len(text) > char_threshold:
        return True
    if (task or {}).get("material"):
        return True
    return kind in ("build", "security", "legal")


def make_probe(task: Optional[dict], prompt: Optional[str], project: str) -> str:
    try:
        choose, complete = _resolve_backend()
        sensitivity = str((task or {}).get("sensitivity") or "standard")
        provider, model, _ = choose("review", agentic=False, need=5, sensitivity=sensitivity)
        probe_prompt = (
            "You are a cheap preflight probe. Do not implement. Return a compact routing brief:\n"
            "- PROMISING: yes/no\n"
            "- MINIMAL_SLICE: the smallest file/symbol/test area likely needed\n"
            "- REUSE: existing helpers or prior pattern keywords to search\n"
            "- RISKS: only the top 2 merge/build risks\n\n"
            "TASK:\n" + str(prompt or "")[:8000]
        )
        res = complete(provider, model, probe_prompt, project=project,
                       timeout=int(os.environ.get("ORCH_ADAPTIVE_PROBE_TIMEOUT", "45")),
                       operation="adaptive_probe", task_class="review",
                       fallback=True)
        text = (res.get("text") or "").strip()
        if not text:
            return ""
        return f"\n\n{MARK} ({res.get('provider')}:{res.get('model')}):\n{text[:1600]}\n"
    except Exception:
        return ""


def inject(task: Optional[dict], prompt: Optional[str], project: str = "orchestrator") -> str:
    if not should_probe(task, prompt):
        return prompt
    probe = make_probe(task, prompt, project)
    return (probe + "\n" + prompt) if probe else prompt
