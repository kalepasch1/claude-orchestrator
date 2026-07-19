#!/usr/bin/env python3
"""
premerge_redteam.py - adversarial red-team gate that runs BEFORE judge.py. A cheap model
probes each diff for security holes, edge cases, injection risks, and auth issues that
tests might miss. Blocks or annotates issues so judge.py and the merge train see them.

Wired into the integrate gate: call redteam(diff, task_prompt) before judge.review().
If the red-team finds a blocker, the merge is held with a detailed explanation.

Uses the cheapest available model (local Ollama first, then deepseek, etc.) to keep
cost near zero. Fail-soft: if all models fail, returns "pass" with a warning.
"""
import os, sys, json, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import model_gateway as mg

MAX_DIFF_CHARS = int(os.environ.get("REDTEAM_MAX_DIFF", "8000"))

REDTEAM_PROMPT = """You are a security-focused red-team reviewer. Analyze this DIFF for:
1. **Injection risks**: SQL injection, shell injection, template injection, path traversal
2. **Auth/authz gaps**: missing permission checks, privilege escalation, hardcoded creds
3. **Secret leaks**: API keys, tokens, passwords in code or comments
4. **Edge cases**: nil/null deref, integer overflow, race conditions, unbounded loops
5. **Supply chain**: suspicious new dependencies, typosquatting package names

Return ONE JSON object:
{{"verdict":"pass"|"block","findings":[{{"severity":"critical"|"high"|"medium"|"low","category":"<1-5 above>","description":"<=1 sentence","line_hint":"<approx line or file>"}}],"summary":"<=2 sentences"}}

verdict="block" ONLY for critical or high severity findings. Medium/low are informational.
TASK CONTEXT: {task}
DIFF:
{diff}"""

_COST_ORDER = ["local", "deepseek", "google", "openai", "claude"]


def _pick_model() -> tuple:
    """Pick the cheapest available model for red-teaming."""
    models = {
        "local": os.environ.get("OLLAMA_MODEL", "llama3.1"),
        "deepseek": os.environ.get("REDTEAM_DEEPSEEK_MODEL", "deepseek-v4-flash"),
        "google": os.environ.get("REDTEAM_GOOGLE_MODEL", "gemini-2.5-flash"),
        "openai": os.environ.get("REDTEAM_OPENAI_MODEL", "gpt-5.4-mini"),
        "claude": "claude-haiku-4-5-20241022",
    }
    avail = set(mg.available())
    for provider in _COST_ORDER:
        if provider in avail:
            return provider, models.get(provider, "")
    return "claude", models["claude"]


def redteam(diff: str, task_prompt: str = "") -> dict:
    """Red-team a diff. Returns {"verdict", "findings", "summary", "provider"}."""
    if not diff or not diff.strip():
        return {"verdict": "pass", "findings": [], "summary": "empty diff", "provider": "none"}

    truncated = diff[:MAX_DIFF_CHARS]
    prompt = REDTEAM_PROMPT.format(task=task_prompt[:500], diff=truncated)
    provider, model = _pick_model()

    try:
        result = mg.complete(provider, model, prompt)
        text = result.get("text", "")
        # extract JSON from response
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            parsed = json.loads(match.group())
            parsed["provider"] = provider
            parsed["cost_usd"] = result.get("cost_usd", 0)
            return parsed
        return {"verdict": "pass", "findings": [], "summary": "could not parse red-team response",
                "provider": provider, "raw": text[:200]}
    except Exception as e:
        return {"verdict": "pass", "findings": [],
                "summary": f"red-team model error (fail-soft pass): {e}",
                "provider": provider}


def gate(diff: str, task_prompt: str = "") -> dict:
    """Integration gate: returns {"allowed": bool, "redteam": result}."""
    result = redteam(diff, task_prompt)
    blocked = result.get("verdict") == "block"
    return {"allowed": not blocked, "redteam": result}


if __name__ == "__main__":
    import sys as _sys
    diff = _sys.stdin.read() if not _sys.stdin.isatty() else "# no diff provided"
    print(json.dumps(gate(diff), indent=2, default=str))
