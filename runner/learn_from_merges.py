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
"""
import os, sys, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

LOOKBACK = int(os.environ.get("MERGE_LEARN_LOOKBACK", "40"))


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
