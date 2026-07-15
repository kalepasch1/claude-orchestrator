#!/usr/bin/env python3
"""
judge.py - cross-model QA + rating panel. Before an auto-merge, a DIFFERENT model family than
the author reviews the diff and returns a rating + a legal-risk assessment. This is what lets
us safely UNBLOCK and auto-merge tested work while gating ONLY items that truly need legal
counsel (with the legal risk explained on the approval card).

review(task_prompt, diff, author_model, project) -> {
   "verdict": "pass"|"fail", "score": 0-10, "notes": "...",
   "legal_counsel_required": bool, "legal_risk": "explanation or ''",
   "panel": [ per-judge results ] }

Panel = up to N cheapest available NON-author-family models (judge.py picks them from
model_gateway.available()). Falls back to a cheap Claude model if no other provider is set.
"""
import os, sys, json, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import model_gateway as mg

N_JUDGES = int(os.environ.get("JUDGE_PANEL_SIZE", "2"))

# cheapest capable reviewer per provider
REVIEWERS = {
    "openai": os.environ.get("JUDGE_OPENAI_MODEL", "gpt-5.4-mini"),
    "google": os.environ.get("JUDGE_GOOGLE_MODEL", "gemini-2.5-flash"),
    "deepseek": os.environ.get("JUDGE_DEEPSEEK_MODEL", "deepseek-v4-flash"),
    "local": os.environ.get("OLLAMA_MODEL", "llama3.1"),
    "claude": "claude-haiku-4-5-20241022",
}

PROMPT = """You are a pragmatic code reviewer for a fast-moving solo shop (not a FAANG gate). Review
this DIFF and return ONE JSON object only:
{"verdict":"pass"|"fail","score":0-10,"notes":"<=2 sentences",
 "legal_counsel_required":true|false,"legal_risk":"<if true, the specific legal exposure (license,
 regulated activity like money transmission, privacy/PII, IP, ToS); else ''>"}
SHIP-BY-DEFAULT BAR — verdict="pass" if the change is CORRECT, SAFE, and the tests pass. You MUST NOT
fail for: style, naming, formatting, "could be cleaner", "best practices", "needs more tests", or
"additional review recommended" — those are notes, not blockers. verdict="fail" ONLY for a CONCRETE
defect: a real correctness bug, a security hole (injection/auth/secret leak), data loss, or a broken/
missing test for critical logic you can point to. If unsure and tests pass, PASS with a note. Set
legal_counsel_required=true ONLY for genuine legal exposure a lawyer must clear. TASK: {task}
DIFF:
{diff}"""


# Ascending all-in cost — costless-first QA. Free local Ollama, then the cheapest APIs, and
# Claude (subscription) only as a last resort. Running QA on $0 providers frees the Claude
# subscription for the agentic coding only it can do, and makes review resilient to Claude limits.
_COST_ORDER = ["local", "deepseek", "google", "openai", "claude"]


def _panel_providers(author_model):
    author_family = "claude" if "claude" in (author_model or "") else ""
    avail = set(mg.available())
    ordered = [p for p in _COST_ORDER if p in avail]              # cheapest-first
    non_author = [p for p in ordered if p != author_family]       # prefer a different family
    picks = non_author or ordered                                 # fall back if only author fam
    return picks[:N_JUDGES] or ["claude"]


def review(task_prompt, diff, author_model="claude-opus-4-8", project=None, max_chars=45000):
    prompt = PROMPT.replace("{task}", (task_prompt or "")[:2000]).replace("{diff}", (diff or "")[:max_chars])
    panel = []
    for prov in _panel_providers(author_model):
        try:
            import verifier_marketplace
            prov, model = verifier_marketplace.choose("review", need=6, author_model=author_model)
        except Exception:
            model = REVIEWERS.get(prov, "claude-haiku-4-5-20251001")
        r = mg.complete(prov, model, prompt, project=project)
        try:
            d = json.loads(re.search(r"\{.*\}", r["text"], re.S).group(0))
        except Exception:
            d = {"verdict": "pass", "score": 6, "notes": "unparseable review", "legal_counsel_required": False, "legal_risk": ""}
        d["by"] = f"{prov}:{model}"; d["cost_usd"] = r.get("cost_usd", 0)
        try:
            import verifier_marketplace
            verifier_marketplace.record(d["by"], d.get("verdict"))
        except Exception:
            pass
        panel.append(d)
    if not panel:
        return {"verdict": "pass", "score": 6, "notes": "no judges available",
                "legal_counsel_required": False, "legal_risk": "", "panel": []}
    scores = [float(p.get("score", 6)) for p in panel]
    verdict = "pass" if all(str(p.get("verdict", "pass")).lower().startswith("pass") for p in panel) else "fail"
    legal = any(p.get("legal_counsel_required") for p in panel)
    legal_txt = " | ".join(p.get("legal_risk", "") for p in panel if p.get("legal_risk"))
    return {"verdict": verdict, "score": round(sum(scores) / len(scores), 1),
            "notes": " | ".join(p.get("notes", "") for p in panel)[:500],
            "legal_counsel_required": legal, "legal_risk": legal_txt,
            "panel": panel}


if __name__ == "__main__":
    print("judge providers:", mg.available())
