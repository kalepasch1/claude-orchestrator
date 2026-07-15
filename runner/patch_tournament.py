#!/usr/bin/env python3
"""Blinded patch tournament scored by validation and exact deployed-value history."""
import hashlib
import math
import os
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed


def _provider(model):
    value = str(model or "").lower()
    if "grok" in value or "xai" in value: return "xai"
    if "groq" in value: return "groq"
    if "deepseek" in value: return "deepseek"
    if value.startswith(("gpt", "o1", "o3", "o4", "o5")): return "openai"
    if "gemini" in value: return "google"
    if value.startswith(("claude", "sonnet", "opus", "haiku")): return "claude"
    return "local"


def anonymous_id(patch):
    return hashlib.sha256(str(patch or "").encode()).hexdigest()[:12]


def score(candidate, history=None):
    patch = str(candidate.get("patch") or candidate.get("text") or "")
    provider = _provider(candidate.get("model") or candidate.get("provider"))
    prior = (history or {}).get(provider, {})
    deployed = float(prior.get("deployed", 0)); trials = float(prior.get("n", 0))
    deployment_prior = (deployed + 1.0) / (trials + 4.0)
    valid = bool(candidate.get("applies", candidate.get("returncode", 1) == 0))
    tests = bool(candidate.get("tests_passed"))
    build = bool(candidate.get("build_passed"))
    nonempty = bool(re.search(r"^(?:diff --git|--- |\+\+\+ )", patch, re.M))
    size_penalty = min(2.0, len(patch) / 100000.0)
    return (4.0 * valid + 4.0 * tests + 3.0 * build + 1.5 * nonempty
            + 3.0 * deployment_prior - size_penalty)


def choose(candidates, history=None):
    blinded = []
    for candidate in candidates or []:
        row = dict(candidate)
        row["anonymous_id"] = anonymous_id(row.get("patch") or row.get("text"))
        row["score"] = round(score(row, history), 6)
        blinded.append(row)
    blinded.sort(key=lambda row: (-row["score"], row["anonymous_id"]))
    if not blinded or not (blinded[0].get("patch") or blinded[0].get("text")):
        return {"winner": None, "ranking": blinded}
    winner = dict(blinded[0])
    winner.pop("provider", None); winner.pop("model", None)
    return {"winner": winner, "ranking": [{"anonymous_id": r["anonymous_id"], "score": r["score"]} for r in blinded]}


def _git(repo, *args, input_text=None, timeout=180):
    return subprocess.run(["git", *args], cwd=repo, input=input_text, capture_output=True,
                          text=True, timeout=timeout)


def _candidate(task, repo, provider, model, test_cmd=""):
    import swarm_executor
    tmp = tempfile.mkdtemp(prefix="patch-arm-")
    added = False
    try:
        if _git(repo, "worktree", "add", "--detach", tmp, "HEAD").returncode != 0:
            return {"provider": provider, "model": model, "patch": "", "applies": False}
        added = True
        try:
            import dependency_prewarm
            dependency_prewarm.link_shared_runtime(repo, tmp)
        except Exception:
            pass
        result = swarm_executor.run_swarm(task.get("prompt", ""), model, provider, tmp,
                                          timeout=float(os.environ.get("ORCH_PATCH_ARM_TIMEOUT", "300")), mode="diff")
        patch = _git(tmp, "diff", "--binary").stdout
        applies = bool(patch) and _git(tmp, "diff", "--check").returncode == 0
        tests = False
        if applies and test_cmd:
            tested = subprocess.run(["bash", "-lc", test_cmd], cwd=tmp, capture_output=True,
                                    text=True, timeout=int(os.environ.get("ORCH_PATCH_TEST_TIMEOUT", "900")))
            tests = tested.returncode == 0
        return {"provider": provider, "model": model, "patch": patch, "applies": applies,
                "tests_passed": tests if test_cmd else applies, "build_passed": False,
                "cost_usd": float(result.get("cost_usd") or 0)}
    except Exception as e:
        return {"provider": provider, "model": model, "patch": "", "applies": False,
                "error": str(e)[:200]}
    finally:
        if added:
            _git(repo, "worktree", "remove", "--force", tmp)
        shutil.rmtree(tmp, ignore_errors=True)


def run_live(task, repo, providers, *, test_cmd="", history=None):
    """Generate isolated arms concurrently, blind-rank them, apply only winner."""
    import swarm_executor
    arms = []
    for provider in providers:
        models = (swarm_executor.PROVIDERS.get(provider) or {}).get("models") or {}
        model = models.get("mid") or models.get("fast") or next(iter(models.values()), "")
        if model:
            arms.append((provider, model))
    candidates = []
    with ThreadPoolExecutor(max_workers=max(1, min(3, len(arms)))) as pool:
        futures = [pool.submit(_candidate, task, repo, provider, model, test_cmd) for provider, model in arms]
        for future in as_completed(futures):
            candidates.append(future.result())
    decision = choose(candidates, history)
    winner = decision.get("winner") or {}
    anon = winner.get("anonymous_id")
    original = next((c for c in candidates if anonymous_id(c.get("patch")) == anon), None)
    if not original or not original.get("applies"):
        return {"returncode": 1, "text": "no valid tournament patch", "ranking": decision.get("ranking", [])}
    check = _git(repo, "apply", "--check", "-", input_text=original["patch"])
    if check.returncode != 0:
        return {"returncode": 1, "text": "winning patch no longer applies", "ranking": decision.get("ranking", [])}
    applied = _git(repo, "apply", "-", input_text=original["patch"])
    return {"returncode": 0 if applied.returncode == 0 else 1, "text": original["patch"],
            "coder": f"tournament:{anon}", "winner_provider": original.get("provider"),
            "winner_model": original.get("model"), "cost_usd": sum(c.get("cost_usd", 0) for c in candidates),
            "ranking": decision.get("ranking", [])}
