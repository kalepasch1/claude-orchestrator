#!/usr/bin/env python3
"""
spec_writer.py - each app maintains its OWN SPEC.md from what actually merged + how it's used, so the
planner's decompositions get sharper over time without you writing specs. A cheap model reads the
repo's CLAUDE.md (learned conventions), recent merged slugs, and any revenue/usage signal, and writes a
concise SPEC.md of invariants + product direction. planner.plan() already reads SPEC.md, so this closes
the loop: outcomes -> spec -> better plans -> better outcomes.

Costless-first; writes SPEC.md at repo root; STABLE wording (it's also a cached prefix). Schedule weekly.
"""
import os, sys, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

PROMPT = """Write/refresh a concise SPEC.md (<=120 lines) for this app: the product's purpose in 2 lines,
the hard INVARIANTS every change must preserve (data, security, correctness), and the current direction.
Base it ONLY on the signals below — do not invent features. Keep wording STABLE (it's a cached prefix).
Output just the SPEC.md contents.

# Learned conventions (from merged work):
{conventions}
# Recently merged changes:
{merges}
# Revenue/usage signal:
{revenue}"""


def run():
    projs = db.select("projects", {"select": "id,name,repo_path"}) or []
    wrote = 0
    for p in projs:
        repo = p.get("repo_path", "")
        if not repo or not os.path.isdir(repo):
            continue
        conv = ""
        cmd_path = os.path.join(repo, "CLAUDE.md")
        if os.path.isfile(cmd_path):
            try: conv = open(cmd_path).read()[:4000]
            except Exception: pass
        merged = db.select("tasks", {"select": "slug", "project_id": f"eq.{p['id']}",
                                     "state": "eq.MERGED", "order": "updated_at.desc", "limit": "15"}) or []
        merges = ", ".join(m["slug"] for m in merged) or "(none yet)"
        rev = (db.select("app_revenue", {"select": "*", "app": f"eq.{p['name']}"}) or [None])[0]
        revs = f"MRR ${rev.get('mrr_usd')}, users {rev.get('active_users')}" if rev else "(no revenue data)"
        prompt = (PROMPT.replace("{conventions}", conv).replace("{merges}", merges)
                  .replace("{revenue}", revs))[:20000]
        try:
            import model_policy, model_gateway
            prov, model, _ = model_policy.choose("plan", agentic=False)
            r = model_gateway.complete(prov, model, prompt)
            spec = (r.get("text") or "").strip()
        except Exception:
            spec = ""
        if len(spec) > 80:
            try:
                with open(os.path.join(repo, "SPEC.md"), "w", encoding="utf-8") as f:
                    f.write(spec[:8000])
                wrote += 1
                print(f"spec_writer: refreshed SPEC.md for {p['name']}")
            except Exception as e:
                print(f"spec_writer: {p['name']} write failed ({e})")
    if not wrote:
        print("spec_writer: nothing to write (no repos/signals yet)")
    return wrote


if __name__ == "__main__":
    run()
