#!/usr/bin/env python3
"""
build_fixer.py — turn a RED build into a targeted, model-generated fix directive.

When integrate()'s build gate fails, instead of dead-ending to a full re-plan, a FAST non-Claude
model (Gemini-flash / DeepSeek / OpenAI, rotated) reads the build error + the diff and emits a
SHORT, concrete fix directive (which file, what to change). That directive is injected into the
task note so the next draft is build-aware — converting "recycled through remediation" into
"self-corrected and shipped". Uses cheap models (esp. Gemini) so it's near-free.

Fail-soft: returns '' on any error, so it can never block the pipeline.
"""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_RR = {"i": 0}


def logpath(slug):
    return os.path.join(tempfile.gettempdir(), f"orch-buildlog-{slug or 'x'}.txt")


def save_log(slug, blog):
    try:
        with open(logpath(slug), "w") as f:
            f.write(blog or "")
    except Exception:
        pass


def load_log(slug):
    try:
        with open(logpath(slug)) as f:
            return f.read()
    except Exception:
        return ""


def _pick_fixer():
    """Rotate across fast non-Claude models good at mechanical build errors (Gemini/DeepSeek/OpenAI)."""
    try:
        import model_gateway
        avail = set(model_gateway.available())
        ring = [("google", os.environ.get("FIXER_GOOGLE_MODEL", "gemini-2.5-flash")),
                ("deepseek", os.environ.get("FIXER_DEEPSEEK_MODEL", "deepseek-v4-flash")),
                ("openai", os.environ.get("FIXER_OPENAI_MODEL", "gpt-5.4-mini"))]
        ring = [(p, m) for p, m in ring if p in avail]
        if not ring:
            return None
        pick = ring[_RR["i"] % len(ring)]
        _RR["i"] += 1
        return pick
    except Exception:
        return None


def fix_directive(build_log, diff="", task_prompt="", project=None):
    """Return a short actionable fix directive for the build error, or '' if unavailable."""
    if os.environ.get("ORCH_BUILD_FIXER", "true").lower() != "true":
        return ""
    if not (build_log or "").strip():
        return ""
    pick = _pick_fixer()
    if not pick:
        return ""
    prov, model = pick
    try:
        import model_gateway
        ask = (
            "A production build FAILED. Read the build error and the code diff, then give a SHORT, "
            "concrete fix: name the exact file(s) and the specific change needed to make the build "
            "pass (fix types/imports/syntax; do not add features). 3-8 bullets, no full code.\n\n"
            "# Build error:\n" + build_log[-4000:]
            + (("\n\n# Diff so far:\n" + diff[-4000:]) if diff else "")
            + (("\n\n# Original task:\n" + task_prompt[:800]) if task_prompt else "")
        )
        res = model_gateway.complete(prov, model, ask, project=project, operation="build_fix",
                                     task_class="review", timeout=60)
        text = (res or {}).get("text", "").strip()
        if text:
            return (f"# The previous attempt FAILED the production build. Fix the build first, per this "
                    f"analysis from {res.get('provider', prov)}:{res.get('model', model)}:\n{text}\n")
    except Exception:
        pass
    return ""


if __name__ == "__main__":
    print("fixer:", _pick_fixer())
