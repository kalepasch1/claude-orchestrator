#!/usr/bin/env python3
"""Verifier marketplace: pick and score cheap/local reviewers by realized outcomes."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import model_catalog


def choose(kind="review", need=6, sensitivity="standard", author_model=""):
    author_provider = ""
    if "claude" in (author_model or ""):
        author_provider = "claude"
    elif "gpt" in (author_model or "") or "openai" in (author_model or ""):
        author_provider = "openai"
    c = model_catalog.choose(kind, need=need, sensitivity=sensitivity, exclude_provider=author_provider)
    if c:
        return c["provider"], c["model"]
    return "claude", "claude-haiku-4-5-20251001"


def record(by, verdict, integrated=False, deployed=False):
    try:
        import db
        provider, _, model = str(by or "").partition(":")
        db.insert("verifier_outcomes", {"provider": provider, "model": model,
                                        "verdict": verdict, "integrated": bool(integrated),
                                        "deployed": bool(deployed)})
    except Exception:
        pass
