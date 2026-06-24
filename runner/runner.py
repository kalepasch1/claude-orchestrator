#!/usr/bin/env python3
"""
runner.py - the Mac engine. Polls Supabase for queued tasks, executes Claude Code in
isolated git worktrees, and streams status/cost/outcomes back to Supabase so the
hosted dashboard updates in realtime. Ties together every feature:

  bandit/model_router  -> cheapest capable model (learned from outcomes)
  account_pool         -> rotate accounts on usage exhaustion
  caching              -> stable cached context prefix (input-token savings)
  knowledge_embed      -> inject relevant prior solutions (semantic reuse)
  verify               -> cheap-model diff review BEFORE integrate
  cost_ledger          -> record $/task (also pushed to Supabase outcomes)

Run on your Mac:
  export SUPABASE_URL=...  SUPABASE_SERVICE_KEY=...   # service key stays on the Mac
  python3 runner.py

It NEVER force-merges: verify-fail or test-fail creates an approval card and stops.
"""
import os, sys, time, json, socket, subprocess, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db, bandit, verify, caching, account_pool, cost_ledger
import knowledge_embed as kb
import regression, budget, speculative, pr_integrate
import context_retrieval, result_cache
import confidence, blast_radius, replay

INTEGRATION_MODE = os.environ.get("INTEGRATION_MODE", "local")  # local | pr
USE_CACHE = os.environ.get("RESULT_CACHE", "true").lower() == "true"
USE_RETRIEVAL = os.environ.get("SCOPED_CONTEXT", "true").lower() == "true"
USE_CONFIDENCE = os.environ.get("CONFIDENCE_GATE", "true").lower() == "true"

CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
RUNNER_ID = os.environ.get("RUNNER_ID", socket.gethostname() + "-" + str(os.getpid()))
POLL = int(os.environ.get("POLL_SECONDS", "5"))
MAX_PARALLEL = int(os.environ.get("MAX_PARALLEL", "2"))
RATE = ("temporarily limiting", "rate limit", "429", "overloaded", "too many requests")
EXHAUST = ("usage limit", "out of credits", "insufficient_quota", "quota")
POOL = account_pool.AccountPool()
_sem = threading.Semaphore(MAX_PARALLEL)
_projects = {}


def projects():
    global _projects
    if not _projects:
        for p in db.select("projects") or []:
            _projects[p["id"]] = p
    return _projects


def set_state(task_id, **kw):
    kw["updated_at"] = "now()"
    db.update("tasks", {"id": task_id}, kw)


def approval(project, kind, title, **kw):
    db.insert("approvals", {"project": project, "kind": kind, "title": title, **kw})


def integrate(repo, branch, base, test_cmd, slug="", verify_notes="", test_summary="passed"):
    # PR-native: push, open PR, let YOUR CI (sfc/gitleaks/vercel) gate, auto-merge on green.
    if INTEGRATION_MODE == "pr":
        r = pr_integrate.open_pr(repo, branch, base, slug, verify_notes, test_summary)
        if not r.get("ok"):
            return "CONFLICT"
        outcome = pr_integrate.wait_and_merge(repo, branch)
        return {"MERGED": "MERGED", "CHECKS_FAILED": "TESTFAIL", "OPEN": "BLOCKED"}.get(outcome, "BLOCKED")
    # local ff-merge
    if subprocess.run(["git", "rebase", base, branch], cwd=repo).returncode != 0:
        subprocess.run(["git", "rebase", "--abort"], cwd=repo)
        return "CONFLICT"
    subprocess.run(["git", "checkout", branch], cwd=repo)
    if subprocess.run(test_cmd, cwd=repo, shell=True).returncode != 0:
        return "TESTFAIL"
    subprocess.run(["git", "checkout", base], cwd=repo)
    subprocess.run(["git", "merge", "--ff-only", branch], cwd=repo)
    return "MERGED"


def run_task(t):
    with _sem:
        proj = projects().get(t["project_id"], {})
        repo = proj.get("repo_path", os.getcwd())
        name = proj.get("name", "repo")
        base = t.get("base_branch", "main")
        slug = t["slug"]
        kind = t.get("kind", "build")
        test_cmd = os.environ.get("TEST_CMD", "npm test")

        # budget guardrail: hold the task if the project hit its monthly cap
        if not budget.allow(name):
            set_state(t["id"], state="BLOCKED", note="budget cap reached")
            return

        # result cache: identical (repo+prompt+commit) work is reused, not re-run
        sig = result_cache.signature(name, t["prompt"], repo, base) if USE_CACHE else None
        if sig:
            hit = result_cache.lookup(sig)
            if hit:
                set_state(t["id"], state="DONE", note=f"cache hit: reused {hit.get('branch')}")
                record(t, name, slug, kind, "cache", POOL.current(), 0, True, False, "", time.time())
                return

        # context prefix + scoped file focus + blast radius + semantic reuse + lessons
        prefix = caching.load_prefix(repo)
        focus = context_retrieval.focus_note(repo, t["prompt"]) if USE_RETRIEVAL else ""
        blast = blast_radius.note_for_task(repo, t["prompt"]) if USE_RETRIEVAL else ""
        prompt = prefix + focus + blast + regression.inject(kb.inject(t["prompt"]))
        t0 = time.time()

        # speculative N-best: race a few approaches, keep the cheapest that passes
        if kind == "speculative":
            env = dict(os.environ); env.update(POOL.env_for(POOL.current()))
            res = speculative.run(repo, slug, base, prompt, test_cmd, env=env)
            w = res["winner"]
            if not w:
                set_state(t["id"], state="BLOCKED", note="no speculative variant passed")
                regression.record(name, slug, kind, "speculative N-best", "all variants failed tests", "")
                record(t, name, slug, kind, "speculative", POOL.current(), 1, False, False, "", t0); return
            result = integrate(repo, w["branch"], base, test_cmd, slug, "n-best winner", "passed")
            set_state(t["id"], state=result, model=w["model"], note=f"speculative winner {w['vslug']} ({w['model']})")
            record(t, name, slug, kind, w["model"], POOL.current(), 1, True, result == "MERGED", "", t0); return
        attempt = 0
        while attempt < 4:
            attempt += 1
            model = t.get("model") or bandit.choose(db, kind, t["prompt"])
            acct = POOL.current()
            set_state(t["id"], state="RUNNING", model=model, attempt=attempt,
                      account=(acct or {}).get("name"))
            subprocess.run([os.path.join(os.path.dirname(__file__), "setup-worktrees.sh"), slug, base],
                           cwd=repo, capture_output=True)
            wt = os.path.join(os.path.dirname(repo), os.path.basename(repo) + "-wt", slug)
            env = dict(os.environ); env.update(POOL.env_for(acct))
            log = subprocess.run(
                [CLAUDE_BIN, "-p", prompt, "--model", model, "--permission-mode", "acceptEdits",
                 "--max-turns", "60", "--output-format", "text"],
                cwd=wt if os.path.isdir(wt) else repo, env=env,
                capture_output=True, text=True)
            out = (log.stdout + log.stderr)
            low = out.lower()
            set_state(t["id"], log_tail=out[-2000:])

            if any(s in low for s in EXHAUST):
                nxt = POOL.mark_exhausted(acct)
                set_state(t["id"], state="RETRY", note=f"account exhausted -> {nxt}")
                if nxt and nxt != (acct or {}).get("name"):
                    attempt -= 1
                continue
            if any(s in low for s in RATE):
                back = min(300, 2 ** attempt * 5)
                set_state(t["id"], state="RETRY", note=f"rate-limited, backoff {back}s")
                time.sleep(min(back, 30)); continue

            tests_ok = log.returncode == 0
            if not tests_ok:
                set_state(t["id"], state="BLOCKED", note="agent run failed")
                regression.record(name, slug, kind, t["prompt"][:500], out[-500:], "agent run failed; re-scope or escalate model")
                record(t, name, slug, kind, model, acct, attempt, False, False, out, t0); return

            # verification swarm BEFORE integrate
            v = verify.review_diff(wt, base)
            if v["verdict"] == "fail":
                set_state(t["id"], state="BLOCKED", note="verify: " + v["notes"])
                approval(name, "verify", f"Verification flagged {slug}",
                         why=v["notes"], risk="cheap-model review wants a human look",
                         detail=out[-3000:])
                regression.record(name, slug, kind, t["prompt"][:500], "verify: " + v["notes"], v["notes"])
                record(t, name, slug, kind, model, acct, attempt, True, False, out, t0); return

            # confidence-gated autonomy: high -> auto-merge; low -> human; high-risk -> two-key
            conf = {"confidence": None}
            if USE_CONFIDENCE:
                decision, conf = confidence.gate(wt, base)
            replay.capture(t["id"], name, slug, kind, model, (acct or {}).get("name"),
                           repo, base, prompt, conf.get("confidence"))
            if USE_CONFIDENCE and decision != "auto":
                req = 2 if decision == "two_key" else 1
                set_state(t["id"], state="BLOCKED",
                          note=f"awaiting {'two-key ' if req == 2 else ''}approval (confidence {conf.get('confidence')})")
                approval(name, "material" if decision == "two_key" else "verify",
                         f"Approve merge of {slug}", why=conf.get("reason"),
                         value="agent work passed tests + verification",
                         risk=("HIGH-RISK path — needs two approvers" if req == 2 else "below auto-merge confidence"),
                         detail=out[-2000:], approvals_required=req)
                record(t, name, slug, kind, model, acct, attempt, True, False, out, t0); return

            result = integrate(repo, f"agent/{slug}", base, test_cmd, slug, v["notes"], "passed")
            POOL.mark_ok(acct)
            integrated = result == "MERGED"
            if integrated and sig:
                result_cache.store(sig, name, slug, f"agent/{slug}", v["notes"])
            set_state(t["id"], state=result, note=f"verify pass; integrate={result} ({INTEGRATION_MODE})")
            if result in ("CONFLICT", "TESTFAIL"):
                approval(name, "integrate", f"{slug} {result.lower()} on integrate",
                         why=f"could not auto-integrate ({result})", detail=out[-2000:])
                regression.record(name, slug, kind, t["prompt"][:500], f"integrate {result}", "stay within file scope; rebase early")
            record(t, name, slug, kind, model, acct, attempt, True, integrated, out, t0)
            return
        set_state(t["id"], state="BLOCKED", note="exhausted retries")


def record(t, project, slug, kind, model, acct, attempt, tests_ok, integrated, out, t0):
    row = cost_ledger_row(project, slug, model, out)
    db.insert("outcomes", {
        "task_id": t["id"], "project": project, "slug": slug, "kind": kind,
        "model": model, "account": (acct or {}).get("name"), "attempts": attempt,
        "rate_limited": any(s in out.lower() for s in RATE),
        "tests_passed": tests_ok, "integrated": integrated,
        "input_tokens": row["input_tokens"], "output_tokens": row["output_tokens"],
        "usd": row["usd"], "wall_ms": int((time.time() - t0) * 1000)})


def cost_ledger_row(project, slug, model, out):
    import re
    def n(s): return int(s.replace(",", ""))
    itok = sum(n(x[1]) for x in re.findall(r"(input|prompt)[ _]tokens[\"':\s]+([0-9,]+)", out, re.I))
    otok = sum(n(x[1]) for x in re.findall(r"(output|completion)[ _]tokens[\"':\s]+([0-9,]+)", out, re.I))
    pin, pout = cost_ledger.PRICES.get(model, (3.0, 15.0))
    return {"input_tokens": itok, "output_tokens": otok,
            "usd": round(itok / 1e6 * pin + otok / 1e6 * pout, 4)}


def main():
    print(f"runner {RUNNER_ID} online -> {os.environ.get('SUPABASE_URL','(set SUPABASE_URL)')}")
    active = []
    while True:
        active = [th for th in active if th.is_alive()]
        try:
            db.heartbeat(RUNNER_ID, socket.gethostname(), len(active))
            if len(active) < MAX_PARALLEL:
                t = db.claim_task(RUNNER_ID)
                if t:
                    th = threading.Thread(target=run_task, args=(t,), daemon=True)
                    th.start(); active.append(th); continue
        except Exception as e:
            print("poll error:", e)
        time.sleep(POLL)


if __name__ == "__main__":
    main()
