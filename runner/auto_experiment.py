#!/usr/bin/env python3
"""
auto_experiment.py - the self-tuning gate. When feedback_review clusters a concrete knob
change, this A/B-tests it (current vs candidate) on a fixed eval set BEFORE the orchestrator
adopts it, and only files "recommended: ADOPT" if the candidate is at least as good and not
materially pricier. Turns worker feedback into validated, low-risk self-improvement.

Auto-experimentable knobs (env-driven, safe to vary): context (CONTEXT_MAX_FILES),
rate_limit (MAX_PARALLEL_CEILING). Other categories (model/prompt/guardrail/strategy) need a
code change, so they're filed for manual review with the evidence attached.

Eval set: runner/evals.json = [{"prompt":"...","check":"shell cmd, exit 0 == success"}].
Degrades gracefully: no evals -> verdict 'no_evals' (manual). Mockable via CLAUDE_BIN.
"""
import os, sys, json, re, subprocess, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db, claude_cli

EVAL_MODEL = os.environ.get("EXPERIMENT_MODEL", "claude-haiku-4-5-20251001")
EVALS_PATH = os.environ.get("ORCH_EVALS", os.path.join(os.path.dirname(__file__), "evals.json"))
COST_TOLERANCE = float(os.environ.get("EXPERIMENT_COST_TOLERANCE", "1.10"))

# category -> (env_knob, default, candidate_fn(current, suggestion))
def _num(s, default):
    m = re.search(r"\b(\d+)\b", s or "")
    return int(m.group(1)) if m else default

KNOBS = {
    "context":    ("CONTEXT_MAX_FILES",   12, lambda cur, sug: _num(sug, int(cur * 1.5))),
    "rate_limit": ("MAX_PARALLEL_CEILING", 4, lambda cur, sug: max(1, _num(sug, cur - 1))),
}


def _run(evals, env_patch):
    saved = dict(os.environ); os.environ.update({k: str(v) for k, v in env_patch.items()})
    passed, cost = 0, 0.0
    try:
        for e in evals:
            with tempfile.TemporaryDirectory() as d:
                r = claude_cli.run(e["prompt"], EVAL_MODEL, cwd=d,
                                   permission="acceptEdits", max_turns=15)
                ok = (subprocess.run(e["check"], cwd=d, shell=True).returncode == 0
                      if e.get("check") else r["returncode"] == 0)
                passed += 1 if ok else 0
                cost += r["cost_usd"]
    finally:
        os.environ.clear(); os.environ.update(saved)
    return (passed / max(1, len(evals))), round(cost, 4)


def evaluate(category, suggestion):
    knob = KNOBS.get(category)
    if not knob:
        db.insert("experiments", {"category": category, "verdict": "no_knob",
                  "detail": f"'{category}' needs a code change; routing to manual review. Suggestion: {suggestion}"})
        return "no_knob"
    env_knob, default, cand_fn = knob
    cur = int(os.environ.get(env_knob, default))
    cand = cand_fn(cur, suggestion)
    if cand == cur or not os.path.exists(EVALS_PATH):
        v = "no_evals" if not os.path.exists(EVALS_PATH) else "inconclusive"
        db.insert("experiments", {"category": category, "knob": env_knob,
                  "current_value": str(cur), "candidate_value": str(cand), "verdict": v,
                  "detail": "no eval set configured" if v == "no_evals" else "candidate equals current"})
        return v
    try:
        evals = json.load(open(EVALS_PATH))
    except Exception:
        evals = []
    if not evals:                                  # empty/invalid eval set -> can't A/B safely
        db.insert("experiments", {"category": category, "knob": env_knob,
                  "current_value": str(cur), "candidate_value": str(cand), "verdict": "no_evals",
                  "detail": "evals.json is empty; add eval tasks to enable A/B self-tuning."})
        return "no_evals"
    cur_s, cur_c = _run(evals, {env_knob: cur})
    cand_s, cand_c = _run(evals, {env_knob: cand})
    adopt = cand_s >= cur_s and cand_c <= cur_c * COST_TOLERANCE
    verdict = "adopt" if adopt else "reject"
    db.insert("experiments", {"category": category, "knob": env_knob,
              "current_value": str(cur), "candidate_value": str(cand),
              "current_score": cur_s, "candidate_score": cand_s,
              "current_cost": cur_c, "candidate_cost": cand_c, "verdict": verdict,
              "detail": f"{env_knob}: {cur}->{cand} | pass {cur_s:.2f}->{cand_s:.2f} | cost ${cur_c}->${cand_c}"})
    db.insert("approvals", {"project": "ORCHESTRATOR", "kind": "self",
              "title": f"{'✅ ADOPT' if adopt else '❌ reject'}: {env_knob} {cur}->{cand} ({category})",
              "why": f"A/B over {len(evals)} evals: pass {cur_s:.2f}->{cand_s:.2f}, cost ${cur_c}->${cand_c}.",
              "value": "Evidence-backed self-tuning from agent feedback." if adopt else "Tested; candidate did not win.",
              "risk": "Apply by setting the env knob on a branch through CI; revertible.",
              "command": f"export {env_knob}={cand}" if adopt else ""})
    return verdict


if __name__ == "__main__":
    print(evaluate(sys.argv[1] if len(sys.argv) > 1 else "context",
                   sys.argv[2] if len(sys.argv) > 2 else "raise to 18"))
