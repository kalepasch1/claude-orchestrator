#!/usr/bin/env python3
"""
learn_from_merges.py - reinforcement from what actually SHIPPED. Every merged change is a positive
example; mining them raises first-attempt success (which compounds: fewer retries -> less Opus, lower
latency, more throughput across every future task).

For each project with recent MERGED work, a cheap model reads the merged diffs and distills:
  * reusable conventions (patterns the team actually uses) -> appended to the repo's CLAUDE.md
    (the cached context prefix, so it makes future builds cheaper AND more on-style), and
  * "do/avoid" rules -> regression memory, so the next agent doesn't relitigate solved decisions.

Non-agentic + costless-first: the distillation runs through the cheapest capable provider (model_policy
-> local/DeepSeek/$0-subscription). Schedule daily. Read-only except appending to CLAUDE.md + memory.

QUALITY GATE (2026-07-08): on 2026-07-08 a rate-limited model_gateway.complete() call returned its
provider's usage-limit banner text ("You've hit your weekly limit...") as if it were a real
distillation, and this module appended it straight into CLAUDE.md/regression memory unfiltered —
polluting the cached context prefix every future task pays for. quality_gate() below is the fix:
nothing reaches CLAUDE.md or regression memory without passing a pattern reject-list, a structural
shape check (must actually look like bullet-point conventions/rules), and a best-effort cheap-model
grading pass. Rejects are quarantined to .runtime/knowledge/rejected.jsonl for later inspection
instead of being silently dropped or silently written.
"""
import os, sys, re, json, time, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

LOOKBACK = int(os.environ.get("MERGE_LEARN_LOOKBACK", "40"))

HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
REJECTED_LOG = os.path.join(HOME, "knowledge", "rejected.jsonl")

# Content matching any of these is never a reusable engineering learning — it's an error banner,
# a refusal/apology, or empty noise that leaked through as if it were real model output.
_FAILURE_PATTERNS = [
    re.compile(r"\b(weekly|daily|monthly|usage)\s+limit\b", re.I),
    re.compile(r"\brate[\s-]?limit(ed)?\b", re.I),
    re.compile(r"\bquota\s+(exceeded|reached)\b", re.I),
    re.compile(r"\bHTTP\s+(Error\s+)?[45]\d\d\b", re.I),
    re.compile(r"\b(Internal Server Error|Not Found|Bad Gateway|Service Unavailable|Too Many Requests)\b", re.I),
    re.compile(r"\bresets?\s+\w+\s+\d", re.I),                 # "resets Jul 8 at 6am" style banners
    re.compile(r"^\s*as an ai\b", re.I),
    re.compile(r"\bas a language model\b", re.I),
    re.compile(r"\bi(?:'m| am) (?:sorry|unable to|not able to)\b", re.I),
    re.compile(r"^\s*i apologi[sz]e\b", re.I),
    re.compile(r"\bI cannot (?:help|assist|provide)\b", re.I),
]

_BULLET_RX = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+\S", re.M)


def quality_gate(text, source=""):
    """Return (accepted: bool, reason: str). Never raises — an error during grading is treated as
    'could not confirm quality' and falls back to the structural checks already passed, not a hard
    reject (the model-grading pass is a confidence booster, not a single point of failure the whole
    learning pipeline depends on)."""
    t = (text or "").strip()
    if not t:
        return False, "empty"
    if len(t) < 20:
        return False, "too short to be a real convention/rule list"
    if len(t) > 4000:
        return False, "too long — likely raw dump, not a distillation"
    for rx in _FAILURE_PATTERNS:
        if rx.search(t):
            return False, f"matched failure/banner pattern: {rx.pattern}"
    bullets = _BULLET_RX.findall(t)
    if len(bullets) < 2:
        return False, "does not look like a bulleted convention/do-avoid list (fewer than 2 bullet lines)"
    graded = _grade_with_cheap_model(t)
    if graded is False:
        return False, "cheap-model grader said this is not a reusable engineering learning"
    return True, "ok" if graded is None else "ok (model-graded)"


def _grade_with_cheap_model(text):
    """Best-effort second opinion. Returns True/False, or None if grading itself is unavailable
    (network/provider error, missing module) — callers must treat None as 'no opinion', not reject."""
    try:
        import model_policy, model_gateway
        prov, model, _ = model_policy.choose("review", agentic=False)
        prompt = ("Is the following a reusable SOFTWARE ENGINEERING learning (a coding convention or "
                  "a do/avoid rule), as opposed to an error message, rate-limit notice, apology, or "
                  "unrelated content? Reply with exactly one word: YES or NO.\n\n" + text[:2000])
        r = model_gateway.complete(prov, model, prompt, project="quality-gate")
        answer = (r.get("text") or "").strip().upper()
        if answer.startswith("YES"):
            return True
        if answer.startswith("NO"):
            return False
        return None
    except Exception:
        return None


def _quarantine(text, source, reason):
    try:
        os.makedirs(os.path.dirname(REJECTED_LOG), exist_ok=True)
        with open(REJECTED_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time(), "source": source, "reason": reason,
                                "text": (text or "")[:2000]}) + "\n")
    except Exception:
        pass  # quarantine logging is best-effort visibility, never blocks the reject decision


def _recent_merged(project_id):
    return db.select("tasks", {"select": "slug,base_branch",
                               "project_id": f"eq.{project_id}", "state": "eq.MERGED",
                               "order": "updated_at.desc", "limit": "10"}) or []


def _merged_diff(repo, slug, base):
    for ref in (f"agent/{slug}", "HEAD"):
        try:
            out = subprocess.check_output(["git", "log", "-1", "-p", "--", ".", ref] if ref == "HEAD"
                                          else ["git", "diff", f"{base}...{ref}"],
                                          cwd=repo, text=True, errors="replace", timeout=20)
            if out.strip():
                return out[:20000]
        except Exception:
            continue
    return ""


def run():
    projs = db.select("projects", {"select": "id,name,repo_path"}) or []
    learned = 0
    for p in projs:
        repo = p.get("repo_path", "")
        if not repo or not os.path.isdir(repo):
            continue
        merged = _recent_merged(p["id"])
        if not merged:
            continue
        diffs = []
        for m in merged[:5]:
            d = _merged_diff(repo, m["slug"], m.get("base_branch") or "main")
            if d:
                diffs.append(f"### {m['slug']}\n{d}")
        if not diffs:
            continue
        prompt = ("From these MERGED diffs, extract (a) 3-6 concise CONVENTIONS this codebase actually "
                  "follows, and (b) 3-6 DO/AVOID rules a future agent should respect to get merged on the "
                  "first try. Output two short bulleted lists only.\n\n" + "\n\n".join(diffs))[:24000]
        # costless-first: cheapest capable provider decides the route
        try:
            import model_policy, model_gateway
            prov, model, _ = model_policy.choose("review", agentic=False)
            r = model_gateway.complete(prov, model, prompt, project=p["name"])
            text = (r.get("text") or "").strip()
        except Exception as e:
            text = ""
        if not text:
            continue
        accepted, reason = quality_gate(text, source=p["name"])
        if not accepted:
            _quarantine(text, p["name"], reason)
            print(f"learn_from_merges: rejected distillation for {p['name']} ({reason})")
            continue
        # append to regression memory (do/avoid) so it's injected into future prompts
        try:
            import regression
            regression.record(p["name"], "merge-lessons", "learn", "merged-diff-distillation",
                              text[:1500], "apply these conventions/rules to get merged first-try")
        except Exception:
            pass
        # append a short, STABLE learned-conventions block to CLAUDE.md (cached prefix)
        try:
            path = os.path.join(repo, "CLAUDE.md")
            block = "\n\n## Learned from merged work (auto)\n" + text[:1500] + "\n"
            with open(path, "a", encoding="utf-8") as f:
                f.write(block)
        except Exception:
            pass
        learned += 1
        print(f"learn_from_merges: distilled lessons for {p['name']} from {len(diffs)} merged diffs")
    if not learned:
        print("learn_from_merges: no recent merged work to learn from yet")
    return learned


if __name__ == "__main__":
    run()
