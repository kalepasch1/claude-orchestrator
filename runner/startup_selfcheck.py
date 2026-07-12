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
Posts firewall/worktree/claimable/ram to runner_health with a status verdict.
"""
import os, sys, socket, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db


def _claimable():
    done = {t["slug"] for t in (db.select("tasks", {"select": "slug", "state": "in.(DONE,MERGED)"}) or [])}
    q = db.select("tasks", {"select": "deps", "state": "eq.QUEUED"}) or []
    return sum(1 for t in q if all(d in done for d in (t.get("deps") or [])))


def run(runner_id="startup"):
    detail = []
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
    return {"status": status, "claimable": claimable, "firewall_ok": firewall_ok}


if __name__ == "__main__":
    run()
