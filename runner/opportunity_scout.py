#!/usr/bin/env python3
"""
opportunity_scout.py - a standing agent that surfaces BETTER ideas continuously. For each
repo it asks a cheap model for RICE-scored 10x opportunities (features, refactors, perf,
DX) and files the top ones through the canonical improvement committee. Never edits code
directly; accepted proposals become normal tasks with QA, merge, and release evidence.
"""
import os, sys, json, subprocess, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db, preference, claude_cli

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
            r = claude_cli.run(PROMPT, MODEL, cwd=repo, timeout=200)
            out = r["text"]
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
            title = f"[RICE {rice(o)}] {o.get('title')}"[:200]
            why = o.get("why", "")
            kind = "proposal"
            # preference gate: suppress low-approval-likelihood proposals
            pref = preference.score(title, why, kind)
            if preference.should_suppress(title, why, kind):
                print(f"  suppressed (pref={pref:.2f}): {o.get('title')}")
                continue
            existing = db.select("improvement_proposals", {
                "select": "id", "app": f"eq.{p['name']}", "title": f"eq.{title}",
                "status": "in.(proposed,for_review,queued)", "limit": "1",
            }) or []
            if existing:
                continue
            value = str(o.get("value") or "Improve verified product value.")
            risk = str(o.get("risk") or "Revert the isolated change on regression.")
            spec = (
                f"IMPROVEMENT HYPOTHESIS (feature; not a measured result): {o.get('title')}\n\n"
                f"Baseline: {why}\n"
                f"Target: {value}\n"
                "Multiplier basis: 2x = compare the measured target with the current baseline; "
                "the opportunity's larger claim remains unproven until post-deploy measurement.\n"
                "Measurement plan: establish the baseline before implementation and compare a seven-day "
                "post-release sample against it.\n"
                f"Rollback: {risk}\n\n"
                "Acceptance tests:\n"
                "- The committee records a concrete implementation boundary and measurable baseline.\n"
                "- The implementation passes regression/build gates and has a verified deployment receipt."
            )
            db.insert("improvement_proposals", {
                "app": p["name"], "surface": "feature", "title": title,
                "current_state": str(why)[:600], "proposal": spec[:1500],
                "expected_multiplier": "2x", "divergent": False,
                "rationale": f"RICE {rice(o)}; predicted review likelihood {pref:.0%}. {risk}"[:800],
                "status": "for_review", "score": rice(o),
            })
            made += 1
    print(f"opportunity scout: filed {made} scored proposals")


if __name__ == "__main__":
    run()
