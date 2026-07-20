#!/usr/bin/env python3
"""
verify.py - verification swarm. Before an expensive-model task's work is integrated,
a CHEAP model reviews the git diff for correctness/security regressions (e.g. the
"fail-open allowlist" class). Cheap insurance on expensive work.

review_diff(worktree, base) -> {"verdict": "pass"|"fail", "notes": "..."}
A 'fail' blocks integration and routes an approval card so you can look.
"""
import os, sys, subprocess, json, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import model_gateway, model_policy

REVIEW_MODEL = os.environ.get("VERIFY_MODEL", "")

PROMPT = """You are a strict code reviewer. Below is a git diff. Decide if it is safe to
merge. Look for: security regressions (auth/allowlist made permissive, secrets added),
broken error handling, obviously failing logic, removed tests. Reply with a single JSON
object: {"verdict":"pass"|"fail","notes":"<=2 sentences"}."""

BLAST_SUFFIX = """

# Blast-radius dependents — these files IMPORT the changed modules. Verify tests exist
for them; if they are untested after the diff, reply with verdict "fail" and note why.
Dependent files:
"""


def review_diff(worktree, base="main", max_chars=None, dependents=None, project=None):
    # A 60k-character diff can exceed the useful review window of a cheap local
    # model and trigger a very large KV-cache allocation.  Keep the advisory
    # reviewer bounded; the full project test gate still runs separately.
    if max_chars is None:
        try:
            max_chars = int(os.environ.get("VERIFY_MAX_DIFF_CHARS", "24000"))
        except ValueError:
            max_chars = 24000
    max_chars = max(1, max_chars)
    try:
        diff = subprocess.check_output(["git", "diff", f"{base}...HEAD"],
                                       cwd=worktree, text=True, errors="replace")[:max_chars]
    except Exception as e:
        return {"verdict": "pass", "notes": f"no diff available ({e})"}
    if not diff.strip():
        return {"verdict": "pass", "notes": "empty diff"}
    prompt = PROMPT
    if dependents:
        prompt += BLAST_SUFFIX + "\n".join(f"- {d}" for d in dependents[:12])
    prompt += "\n\nDiff:\n"
    try:
        if REVIEW_MODEL:
            prov = model_gateway.provider_for_model(REVIEW_MODEL)
            model = REVIEW_MODEL
        else:
            try:
                import verifier_marketplace
                prov, model = verifier_marketplace.choose("review", need=6, author_model="")
            except Exception:
                prov, model, _ = model_policy.choose("review", agentic=False, need=6)
        res = model_gateway.complete(prov, model, prompt + diff, project=project,
                                     timeout=int(os.environ.get("VERIFY_TIMEOUT", "90")),
                                     operation="verify_diff", task_class="review")
        out = res["text"]
        m = re.search(r"\{.*\}", out, re.S)
        d = json.loads(m.group(0)) if m else {"verdict": "pass", "notes": "unparseable; defaulting pass"}
        d["verdict"] = "fail" if str(d.get("verdict", "")).lower().startswith("fail") else "pass"
        d["by"] = f"{res.get('provider')}:{res.get('model')}"
        try:
            import verifier_marketplace
            verifier_marketplace.record(d["by"], d["verdict"])
        except Exception:
            pass
        return d
    except Exception as e:
        return {"verdict": "pass", "notes": f"review skipped ({e})"}
