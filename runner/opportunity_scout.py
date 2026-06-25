#!/usr/bin/env python3
"""
opportunity_scout.py - a standing agent that surfaces BETTER ideas continuously. For each
repo it asks a cheap model for RICE-scored 10x opportunities (features, refactors, perf,
DX) and files the top ones as proposal cards. Never edits code - just proposes, so good
ideas keep arriving for you to approve. Schedule weekly.
"""
import os, sys, json, subprocess, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db, preference

CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
MODEL = os.environ.get("SCOUT_MODEL", "claude-haiku-4-5-20251001")

PROMPT = """WITHOUT editing files, scan this repo and propose the TOP 3 highest-leverage
opportunities (a 10x feature, an architectural simplification, a perf/cost win, or a DX
upgrade). For each, output one JSON object per line:
{"title":"...","why":"problem","value":"expected win, quantified","risk":"risk+test",
 "reach":1-10,"impact":1-10,"confidence":0.0-1.0,"effort_days":number}
Be specific to THIS codebase; no trivial nits."""


def rice(o):
    try:
        return round(o["reach"] * o["impact"] * o["confidence"] / max(0.5, o["effort_days"]), 1)
    except Exception:
        return 0.0


def run():
    made = 0
    for p in db.select("projects", {"select": "name,repo_path"}) or []:
        repo = p["repo_path"]
        if not os.path.isdir(repo):
            continue
        try:
            out = subprocess.check_output([CLAUDE_BIN, "-p", PROMPT, "--model", MODEL,
                                           "--output-format", "text"], cwd=repo, text=True, timeout=200)
        except Exception:
            continue
        ideas = []
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    ideas.append(json.loads(line))
                except Exception:
                    pass
        for o in sorted(ideas, key=rice, reverse=True)[:3]:
            title = f"[RICE {rice(o)}] {o.get('title')}"
            why = o.get("why", "")
            kind = "proposal"
            # preference gate: suppress low-approval-likelihood proposals
            pref = preference.score(title, why, kind)
            if preference.should_suppress(title, why, kind):
                print(f"  suppressed (pref={pref:.2f}): {o.get('title')}")
                continue
            db.insert("approvals", {"project": p["name"], "kind": kind,
                                    "title": title, "why": why,
                                    "value": o.get("value"), "risk": o.get("risk"),
                                    "command": "",
                                    "detail": f"predicted approval likelihood: {pref:.0%}"})
            made += 1
    print(f"opportunity scout: filed {made} scored proposals")


if __name__ == "__main__":
    run()
