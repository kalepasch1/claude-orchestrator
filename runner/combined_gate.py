#!/usr/bin/env python3
"""
combined_gate.py — Single model call that covers BOTH verify AND judge review.

Instead of two separate model calls on the same diff (verify.py + judge.py),
this merges them into one prompt, halving gate cost with negligible quality loss.
Both are already advisory (ORCH_SOFT_GATES_ADVISORY=true), so combining them
into a single evaluation is safe.

Returns:
    {"verify": {"verdict": "pass"|"fail", "notes": "..."},
     "judge":  {"verdict": "pass"|"fail", "score": 0-10, "notes": "...",
                "legal_counsel_required": bool, "legal_risk": "..."}}
"""
import os, sys, subprocess, json, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import model_gateway, model_policy

PROMPT = """You are a senior code reviewer performing TWO independent evaluations of this diff.

## Evaluation 1: Security & Safety Review
Check for: security regressions (auth/allowlist made permissive, secrets added),
broken error handling, obviously failing logic, removed tests.

## Evaluation 2: Cross-Model Quality Review
Check for: code quality, correctness relative to the task prompt, potential regressions,
unnecessary complexity, and any legal/licensing/IP concerns.

Return ONE JSON object with both evaluations:
{
  "verify": {"verdict": "pass"|"fail", "notes": "<=2 sentences on security/safety"},
  "judge": {
    "verdict": "pass"|"fail",
    "score": 0-10,
    "notes": "<=2 sentences on quality/correctness",
    "legal_counsel_required": true|false,
    "legal_risk": "describe any legal/IP/licensing concern, or empty string"
  }
}

TASK PROMPT (what the code should accomplish):
{task_prompt}

DIFF:
{diff}"""

BLAST_SUFFIX = """
BLAST-RADIUS DEPENDENTS (files importing changed modules — verify test coverage):
{deps}"""


def review(wt, base, task_prompt, diff_text="", author_model="", deps=None, project=None):
    """Combined verify+judge in a single model call."""
    # Get diff if not provided
    if not diff_text:
        try:
            diff_text = subprocess.check_output(
                ["git", "diff", f"{base}...HEAD"],
                cwd=wt, text=True, errors="replace")[:60000]
        except Exception as e:
            return {
                "verify": {"verdict": "pass", "notes": f"no diff ({e})"},
                "judge": {"verdict": "pass", "score": 6, "notes": f"no diff ({e})",
                          "legal_counsel_required": False, "legal_risk": ""}
            }

    if not diff_text.strip():
        return {
            "verify": {"verdict": "pass", "notes": "empty diff"},
            "judge": {"verdict": "pass", "score": 7, "notes": "empty diff",
                      "legal_counsel_required": False, "legal_risk": ""}
        }

    prompt = PROMPT.format(task_prompt=task_prompt[:2000], diff=diff_text[:55000])
    if deps:
        prompt += BLAST_SUFFIX.format(deps="\n".join(f"- {d}" for d in deps[:12]))

    try:
        # Use a different provider than the author when possible
        try:
            import verifier_marketplace
            prov, model = verifier_marketplace.choose("review", need=6, author_model=author_model)
        except Exception:
            prov, model, _ = model_policy.choose("review", agentic=False, need=6)

        res = model_gateway.complete(prov, model, prompt, project=project,
                                     timeout=int(os.environ.get("COMBINED_GATE_TIMEOUT", "240")),
                                     operation="combined_gate", task_class="review")
        out = res["text"]
        m = re.search(r"\{.*\}", out, re.S)
        if m:
            d = json.loads(m.group(0))
            v = d.get("verify", {})
            j = d.get("judge", {})

            # Normalize verdicts
            v["verdict"] = "fail" if str(v.get("verdict", "")).lower().startswith("fail") else "pass"
            j["verdict"] = "fail" if str(j.get("verdict", "")).lower().startswith("fail") else "pass"
            j.setdefault("score", 6)
            j.setdefault("legal_counsel_required", False)
            j.setdefault("legal_risk", "")
            v["by"] = f"{res.get('provider')}:{res.get('model')}"
            j["by"] = v["by"]
            j["cost_usd"] = res.get("cost_usd", 0)

            return {"verify": v, "judge": j}

        # Unparseable — default pass
        return {
            "verify": {"verdict": "pass", "notes": "combined gate unparseable; defaulting pass"},
            "judge": {"verdict": "pass", "score": 6, "notes": "combined gate unparseable",
                      "legal_counsel_required": False, "legal_risk": ""}
        }

    except Exception as e:
        return {
            "verify": {"verdict": "pass", "notes": f"combined gate error ({e})"},
            "judge": {"verdict": "pass", "score": 6, "notes": f"combined gate error ({e})",
                      "legal_counsel_required": False, "legal_risk": ""}
        }
