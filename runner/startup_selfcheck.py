#!/usr/bin/env python3
"""
startup_selfcheck.py - run ONCE at boot (and callable anytime). Asserts the invariants that, when
violated, silently stall the whole system, and AUTO-HEALS what it can, then posts a health line to
runner_health so a silent stall can never go unseen again.

Checks + heals:
  1. Billing firewall on (API keys stripped)      -> assert (already enforced by subscription_guard).
  2. 0 locked/stale agent worktrees               -> free them (worktree_gc) so merges aren't blocked.
  3. No stale RUNNING zombies (updated > 30m)      -> reclaim to QUEUED.
  4. >= 1 claimable task                           -> if 0 and queue non-empty, run dagfix/unstick.
  5. RAM ok for at least 1 task                    -> if starved, log it (owner frees RAM / gate is tuned).
  6. Claude trust dialog pre-accepted for repo     -> set hasTrustDialogAccepted for the repo AND
     its <repo>-wt worktree root in every provisioned profile's $CLAUDE_CONFIG_DIR/.claude.json.
     Only that one boolean is ever written — never tokens, keys, or permissions.allow entries.
Posts firewall/worktree/claimable/ram to runner_health with a status verdict.
"""
import json, os, sys, socket, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db


def _default_claude_cfg():
    """Path of the Claude Code config file THIS process's agents actually read.

    Claude Code reads $CLAUDE_CONFIG_DIR/.claude.json, not always ~/.claude/.claude.json.
    account_pool gives each login profile its own config_dir (e.g. ~/.claude-heretomorrow),
    so hardcoding ~/.claude wrote trust to a file the agent never opened.
    """
    return os.path.join(
        os.path.expanduser(os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude"), ".claude.json"
    )


_CLAUDE_CFG = _default_claude_cfg()

# The ONLY key this module is ever allowed to write into a Claude config file.
# Trust acceptance must never carry credentials, API keys, or a broad
# permissions.allow list into config — that is what got the original task quarantined.
_TRUST_KEY = "hasTrustDialogAccepted"


def _account_cfg_paths():
    """Config files of every provisioned login profile (fail-soft, never creates dirs).

    Returns only files whose parent directory already exists, so an unprovisioned
    profile is skipped instead of being half-created with a stub config.
    """
    paths = []
    try:
        import account_pool
        for a in (account_pool._get_pool().accts or []):
            d = a.get("config_dir")
            if d and (a.get("type") or "login") == "login":
                paths.append(os.path.join(os.path.expanduser(d), ".claude.json"))
    except Exception:
        pass
    return paths


def _trust_cfg_paths():
    """Deduped list of config files to pre-accept trust in."""
    out, seen = [], set()
    for p in [_CLAUDE_CFG, _default_claude_cfg()] + _account_cfg_paths():
        p = os.path.abspath(os.path.expanduser(p))
        if p in seen:
            continue
        seen.add(p)
        if os.path.isdir(os.path.dirname(p)):
            out.append(p)
    return out


def _trust_repo_paths(repo_path=None):
    """The repo root plus the sibling worktree root agent branches are checked out into.

    Agent worktrees live at <repo>-wt/<slug>; Claude Code trusts per project path, so
    trusting only the repo root left every fresh worktree untrusted — which is exactly
    how `agent/<slug>` branches went missing after repeated rebuilds.
    """
    if repo_path is None:
        repo_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    repo_path = os.path.abspath(os.path.expanduser(repo_path))
    return [repo_path, repo_path + "-wt"]


def _accept_trust(repo_path=None, cfg_path=None):
    """Pre-accept the Claude Code trust dialog for a repo path in ONE config file (fail-soft).

    Writes only `hasTrustDialogAccepted` and leaves every other key untouched. Returns
    True only if the file was actually modified.
    """
    if repo_path is None:
        repo_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    target = cfg_path or _CLAUDE_CFG
    try:
        cfg = {}
        try:
            with open(target) as f:
                cfg = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        if not isinstance(cfg, dict):
            cfg = {}
        projects = cfg.setdefault("projects", {})
        entry = projects.setdefault(repo_path, {})
        if entry.get(_TRUST_KEY):
            return False          # already trusted -> do not rewrite the file
        entry[_TRUST_KEY] = True
        with open(target, "w") as f:
            json.dump(cfg, f, indent=2)
        return True
    except Exception:
        # Fail-soft: an unwritable/absent config dir must never stall the selfcheck.
        return False


def accept_trust_everywhere(repo_path=None):
    """Accept trust for the repo AND its worktree root across every provisioned profile.

    Returns the number of (config file, path) pairs actually updated.
    """
    changed = 0
    for cfg in _trust_cfg_paths():
        for path in _trust_repo_paths(repo_path):
            if _accept_trust(path, cfg_path=cfg):
                changed += 1
    return changed


def _claimable():
    """Return the count of QUEUED tasks whose dependencies are all satisfied (DONE or MERGED).

    Used by the selfcheck to verify the pipeline is not stalled — if zero tasks are claimable
    but the queue is non-empty, deps may be stuck or a DAG cycle exists."""
    done = {t["slug"] for t in (db.select("tasks", {"select": "slug", "state": "in.(DONE,MERGED)"}) or [])}
    q = db.select("tasks", {"select": "deps", "state": "eq.QUEUED"}) or []
    return sum(1 for t in q if all(d in done for d in (t.get("deps") or [])))


def run(runner_id="startup"):
    detail = []
    contract_ok = False
    try:
        import runtime_contract
        proof = runtime_contract.check()
        contract_ok = bool(proof["ok"])
        if not contract_ok:
            detail.append("runtime contract: " + proof["detail"])
    except Exception as e:
        detail.append(f"runtime contract err: {e}")
    # 1) firewall
    firewall_ok = False
    try:
        import subscription_guard
        a = subscription_guard.audit()
        firewall_ok = not a["api_keys_present"] or a["api_allowed"]
        if not firewall_ok:
            subscription_guard.enforce(); firewall_ok = True; detail.append("firewall re-enforced")
    except Exception as e:
        detail.append(f"firewall check err: {e}")

    # 2) free locked/stale worktrees
    locked = 0
    try:
        import worktree_gc
        locked = worktree_gc.run()
    except Exception as e:
        detail.append(f"worktree_gc err: {e}")

    # 3) reclaim stale RUNNING zombies
    cleared = 0
    try:
        cutoff = (datetime.datetime.utcnow() - datetime.timedelta(minutes=30)).isoformat()
        stale = db.select("tasks", {"select": "id,account", "state": "eq.RUNNING",
                                    "updated_at": f"lt.{cutoff}", "limit": "100"}) or []
        for t in stale:
            # COWORK DISPATCH: skip tasks claimed by Cowork sessions
            if (t.get("account") or "").startswith("cowork-"):
                continue
            db.update("tasks", {"id": t["id"]}, {"state": "QUEUED", "account": None,
                      "note": "self-check: reclaimed stale RUNNING zombie"})
        cleared = len([t for t in stale if not (t.get("account") or "").startswith("cowork-")])
    except Exception as e:
        detail.append(f"zombie sweep err: {e}")

    # 4) claimable — if none but queue non-empty, unstick + dagfix
    claimable = _claimable()
    if claimable == 0 and (db.select("tasks", {"select": "id", "state": "eq.QUEUED", "limit": "1"}) or []):
        try:
            import dag_optimizer, periodic
            dag_optimizer.optimize(); periodic.run_unstick(); claimable = _claimable()
            detail.append("ran dagfix+unstick to free claimable work")
        except Exception as e:
            detail.append(f"unblock err: {e}")

    # 5) RAM
    ram = None
    try:
        import resource_governor
        ram = resource_governor.ram_free_gb()
        ok, why = resource_governor.can_claim(0)
        if not ok:
            detail.append(f"RAM-starved: {why}")
    except Exception:
        pass

    # 6) pre-accept trust dialog for this repo AND its worktree root, in every provisioned
    #    login profile's CLAUDE_CONFIG_DIR — an untrusted profile makes Claude Code ignore
    #    .claude/settings.local.json and stall before it ever creates the agent branch.
    try:
        n = accept_trust_everywhere()
        if n:
            detail.append(f"trust accepted for {n} repo/profile path(s)")
    except Exception:
        pass

    status = "ok" if (firewall_ok and claimable > 0 and (ram is None or ram > 2)) else "degraded"
    try:
        db.insert("runner_health", {"runner_id": runner_id, "hostname": socket.gethostname(),
                  "firewall_ok": firewall_ok, "locked_worktrees": locked, "claimable": claimable,
                  "ram_free_gb": ram, "stale_running_cleared": cleared,
                  "status": status, "detail": "; ".join(detail)[:500]})
    except Exception:
        pass
    print(f"[self-check] firewall={firewall_ok} freed_worktrees={locked} zombies={cleared} "
          f"claimable={claimable} ram={ram} -> {status}. {'; '.join(detail)}")
    return {"status": status, "claimable": claimable, "firewall_ok": firewall_ok,
            "runtime_contract_ok": contract_ok}


if __name__ == "__main__":
    run()
