#!/usr/bin/env python3
"""
speculative.py - N-best execution for hard/high-value tasks. Runs several approaches in
parallel isolated worktrees, tests each, and keeps the CHEAPEST one that passes (discards
the rest). Trades a little money for big quality/latency wins on gnarly work.

Enable per task with kind='speculative' (or env SPECULATIVE_N>1). Variants differ by model
so you get a Haiku/Sonnet/Opus race; first-correct-cheapest wins.
"""
import os, sys, subprocess, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import model_router, claude_cli, branch_lease

PRICE_RANK = {model_router.HAIKU: 1, model_router.SONNET: 2, model_router.OPUS: 3}


def _variant(repo, slug, base, model, prompt, test_cmd, results, idx, env, task):
    vslug = f"{slug}-v{idx}"
    branch = f"agent/{vslug}"
    lease = branch_lease.acquire(task, repo, branch, base)
    if not lease:
        results[idx] = {"vslug": vslug, "branch": branch, "model": model,
                        "passed": False, "price": PRICE_RANK.get(model, 2), "cost_usd": 0,
                        "error": "branch lease held"}
        return
    setup = subprocess.run(
        [os.path.join(os.path.dirname(__file__), "setup-worktrees.sh"), vslug, base,
         str(task["id"]), lease["token"]], cwd=repo, capture_output=True,
    )
    wt = os.path.join(os.path.dirname(repo), os.path.basename(repo) + "-wt", vslug)
    if setup.returncode != 0 or not os.path.isdir(wt):
        branch_lease.release(task["id"], branch)
        results[idx] = {"vslug": vslug, "branch": branch, "model": model,
                        "passed": False, "price": PRICE_RANK.get(model, 2), "cost_usd": 0,
                        "error": "worktree owner guard"}
        return
    try:
        r = claude_cli.run(prompt, model, cwd=wt if os.path.isdir(wt) else repo, env=env,
                           max_turns=60, permission="acceptEdits")
        passed = r["returncode"] == 0 and subprocess.run(test_cmd, cwd=wt, shell=True,
                                                         capture_output=True).returncode == 0
        results[idx] = {"vslug": vslug, "branch": branch, "model": model,
                        "passed": passed, "price": PRICE_RANK.get(model, 2),
                        "cost_usd": r["cost_usd"]}
        # Keep a passing winner leased through integration. Losing branches can
        # be released immediately; set_state releases every remaining variant.
        if not passed:
            branch_lease.release(task["id"], branch)
    except Exception as exc:
        branch_lease.release(task["id"], branch)
        results[idx] = {"vslug": vslug, "branch": branch, "model": model,
                        "passed": False, "price": PRICE_RANK.get(model, 2), "cost_usd": 0,
                        "error": str(exc)[:200]}


def run(repo, slug, base, prompt, test_cmd, models=None, env=None, task=None):
    if not task or not task.get("id") or not task.get("project_id"):
        return {"winner": None, "all": [], "error": "task identity required for branch lease"}
    models = models or [model_router.HAIKU, model_router.SONNET, model_router.OPUS]
    env = env or dict(os.environ)
    results = {}
    threads = [threading.Thread(target=_variant,
               args=(repo, slug, base, m, prompt, test_cmd, results, i, env, task), daemon=True)
               for i, m in enumerate(models)]
    for t in threads: t.start()
    for t in threads: t.join()
    winners = sorted([r for r in results.values() if r["passed"]], key=lambda r: r["price"])
    return {"winner": winners[0] if winners else None,
            "all": list(results.values())}
