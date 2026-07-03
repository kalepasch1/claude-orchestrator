#!/usr/bin/env python3
"""
periodic.py - coordinator for all scheduled periodic jobs.
Called by launchd (or manually) with a single job argument.

Jobs:
  spec    - spec drift check across all repos (schedule: weekly)
  chaos   - chaos resilience drills (schedule: weekly, staging only)
  txn     - cross-repo transaction coordinator (schedule: every 5 min)
  scout   - opportunity scout: RICE-scored proposals (schedule: weekly)
  deploy  - canary-gated nightly deploy window (schedule: nightly)
  roi     - update project concurrency_weight from ROI (schedule: daily)

Usage:
  python3 periodic.py spec
  python3 periodic.py txn
"""
import os, sys, subprocess, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db


def run_spec():
    import spec as spec_mod
    rows = db.select("projects", {"select": "*"}) or []
    for p in rows:
        repo = p.get("repo_path", "")
        name = p.get("name", "?")
        if not os.path.isdir(repo):
            print(f"spec {name}: repo not found at {repo}")
            continue
        result = spec_mod.check(repo, name, p["id"])
        print(f"spec {name}: {result or 'no SPEC.md'}")


def run_chaos():
    import chaos
    if not os.environ.get("CHAOS_ENABLED", "").lower() == "true":
        print("chaos: CHAOS_ENABLED not set — skipping (safe; set in a staging env only)")
        return
    for drill in ["stale-runner", "fake-fail"]:
        result = chaos.run(drill)
        print(f"chaos {drill}: {result}")
    time.sleep(60)
    _assert_chaos_recovery()


def _assert_chaos_recovery():
    runners = db.select("runner_heartbeats", {"select": "*"}) or []
    chaos_runner = next((r for r in runners if r["runner_id"] == "chaos-drill"), None)
    # Assert: chaos-drill runner is present (injected) with old timestamp (dashboard should show OFFLINE)
    if chaos_runner:
        db.insert("approvals", {
            "project": "CHAOS", "kind": "self",
            "title": "Chaos drill RESULT: stale-runner assertion",
            "why": "chaos-drill runner was injected with a stale timestamp.",
            "value": "PASS — runner was visible; verify dashboard shows it OFFLINE (red dot).",
            "risk": "If green: heartbeat TTL logic is broken.",
            "status": "pending"
        })
        print("chaos assert: stale-runner injection visible — verify dashboard shows it OFFLINE")
    else:
        print("chaos assert: WARN — stale-runner not found in heartbeats")

    chaos_approvals = db.select("approvals", {
        "select": "id", "project": "eq.CHAOS",
        "status": "eq.pending", "limit": "5"
    }) or []
    if chaos_approvals:
        print(f"chaos assert: fake-fail PASS — {len(chaos_approvals)} chaos card(s) in inbox")
    else:
        print("chaos assert: fake-fail WARN — no CHAOS approval in inbox")


def run_txn():
    import transaction
    txns_list = db.select("txns", {"select": "*", "status": "eq.pending"}) or []
    if not txns_list:
        print("txn: no pending transactions")
        return
    for txn in txns_list:
        txn_id = txn["id"]
        result = transaction.resolve(txn_id)
        print(f"txn {txn_id}: {result}")
        if "ready: integrate" in result:
            _ff_merge_txn(txn_id)
        elif "aborted" in result:
            db.update("txns", {"id": txn_id}, {"status": "aborted", "resolved_at": "now()"})


def _ff_merge_txn(txn_id):
    import transaction
    members = transaction.members(txn_id)
    all_ok = True
    for m in members:
        proj_rows = db.select("projects", {"select": "*", "id": f"eq.{m['project_id']}"}) or []
        repo = (proj_rows[0] if proj_rows else {}).get("repo_path", "")
        if not repo or not os.path.isdir(repo):
            continue
        r = subprocess.run(["git", "merge", "--ff-only", f"agent/{m['slug']}"],
                           cwd=repo, capture_output=True)
        if r.returncode != 0:
            all_ok = False
            db.update("tasks", {"id": m["id"]},
                      {"state": "BLOCKED", "note": f"txn:{txn_id} ff-merge failed"})
            print(f"txn {txn_id}: ff-merge FAILED for {m['slug']}")
        else:
            print(f"txn {txn_id}: merged {m['slug']}")
    status = "merged" if all_ok else "aborted"
    db.update("txns", {"id": txn_id}, {"status": status, "resolved_at": "now()"})
    print(f"txn {txn_id}: {status}")


def run_scout():
    import opportunity_scout
    opportunity_scout.run()


def run_deploy():
    import deploy_window
    deploy_window.run()


def run_batch():
    import batch_pass
    batch_pass.run()


def run_unstick():
    """Safety-net sweep (dependency resilience): requeue TRANSIENT-BLOCKED tasks under the retry
    cap so a foundation task that died on a network blip / notional budget cap can never freeze
    its whole dependency subtree again. Terminal blocks (agent/verify/judge/legal) are left alone.
    This automates the manual requeue that was needed to un-jam `tomorrow`."""
    import retry_policy
    limit = int(os.environ.get("UNSTICK_LIMIT", "60"))
    blocked = db.select("tasks", {"select": "id,slug,note,transient_retries,project_id",
                                  "state": "eq.BLOCKED", "limit": str(limit * 3)}) or []
    requeued = terminal = capped = 0
    for t in blocked:
        d = retry_policy.decide(t.get("note") or "", t.get("transient_retries") or 0)
        if d["action"] == "requeue":
            if requeued >= limit:
                break
            db.update("tasks", {"id": t["id"]},
                      {"state": "QUEUED", "note": d["note"],
                       "transient_retries": d["transient_retries"], "updated_at": "now()"})
            requeued += 1
        elif retry_policy.classify(t.get("note") or "") == "transient":
            capped += 1  # transient but over the retry cap -> leave for a human
        else:
            terminal += 1
    print(f"unstick: requeued {requeued} transient-blocked, {capped} over-cap, {terminal} terminal (left alone)")


def run_dagfix():
    """Keep the dependency graph healthy: drop ghost/redundant dep edges, flag true orphans."""
    import dag_optimizer
    dag_optimizer.optimize()


def run_selftune():
    """Outcome-driven autonomy tuning: nudge per-project confidence thresholds from real results."""
    import self_tune
    self_tune.run(apply=True)


def run_batchmech():
    """Fold independent same-repo mechanical tasks into single agent runs (cold-start savings)."""
    import batch_mechanical
    batch_mechanical.apply()


def run_releasetrain():
    """Accumulate agent work on staging, QA it, release to prod (main/master) as a batch."""
    import release_train; release_train.run()


def run_deployverify():
    """Confirm each Vercel prod deploy; auto-rollback to last-good on failure (no downtime)."""
    import deploy_verify; deploy_verify.run()


def run_worktreegc():
    """Remove leftover agent worktrees so branches are free to merge (fixes phantom CONFLICTs)."""
    import worktree_gc; worktree_gc.run()


def run_stripe():
    import stripe_revenue; stripe_revenue.run()


def run_ownerreport():
    import owner_report; owner_report.run()


def run_pushdecisions():
    """Fan every new decision/action out to email + Smarter (source-of-truth notifications)."""
    import approval_push
    approval_push.run()


def run_roadmap():
    import roadmap; roadmap.run()


def run_selfheal():
    import self_heal; self_heal.run()


def run_newapp():
    import new_app; new_app.run()


def run_autopilot():
    import autopilot; autopilot.run()


def run_abedge():
    import ab_edge; ab_edge.run()


def run_objective():
    """Meta-controller: measure the north-star and tune one knob toward it (revert regressions)."""
    import objective_optimizer; objective_optimizer.run()


def run_remediate():
    """Drive BLOCKED to zero: requeue transient/conflict, escalate+sharpen review/no-op fails, human-card the rest."""
    import auto_remediate; auto_remediate.run()


def run_selfcheck():
    """Assert + auto-heal core invariants; post a health line."""
    import startup_selfcheck; startup_selfcheck.run("periodic")


def run_improve():
    """Always-on '20-500X better?' loop: auto-queue non-divergent improvements, queue business-model ones for review."""
    import improvement_miner; improvement_miner.run()


def run_improvemeasure():
    """Learn which KINDS of improvements actually pay off; bias future mining toward them."""
    import improvement_measure; improvement_measure.run()


def run_committees():
    """Convene expert committees (Legal, BizDev/Marketing, Finance, Product, Security, Growth, Risk)
    on business-model proposals + legal/strategic decisions."""
    import committees; committees.run()


def run_committeecal():
    """Committee memory: reweight committees + individual seats by how well past verdicts predicted outcomes."""
    import committees; committees.calibrate()


def run_committeedocket():
    """Continuous docket: committees proactively re-review shipped features and act when evidence has moved."""
    import committees; committees.docket()


def run_committeerollout():
    """Staged rollout controller: advance healthy canaries (canary->ramp->full) and auto-rollback regressions."""
    import committees; committees.rollout_advance(); committees.conclude_experiments()


def run_committeeboard():
    """Portfolio bandit: continuously shift build effort toward the highest realized-reward app (with
    exploration), and mine fresh experiment hypotheses so the A/B pipeline never runs dry."""
    import committees; committees.board_bandit(); committees.mine_hypotheses()


def run_committeekg():
    """Cross-committee knowledge graph: index opinions/precedents/dissents so panels can pull related priors."""
    import committees; committees.build_kg()


def run_committeemeta():
    """Meta-committee: review the committee system itself and recalibrate autonomously; log structural ideas."""
    import committees; committees.meta_review()


def run_committeewatch():
    """Event-driven watch: scan external reg/security/competitor signals and re-open the docket on material ones."""
    import committees; committees.watch_scan()


def run_committeeminutes():
    """Plain-English board minutes so the owner can skim the whole autonomous operation in 60 seconds."""
    import committees; committees.board_minutes()


def run_committeedigest():
    """Weekly owner brief of the sharpest committee dissents, reversals, and least-confident calls."""
    import committees; committees.dissent_digest()


def run_decisionbriefs():
    """Generate war-room/negotiation-grade briefs for new legal/strategic decisions."""
    import decision_engine; decision_engine.run()


def run_legaltriage():
    """Classify legal cards routine/elevated/novel; auto-clear routine (if enabled), escalate novel."""
    import legal_triage
    legal_triage.run()


def run_revattr():
    """Snapshot revenue + attribute merges to revenue movement (which work pays off)."""
    import revenue_attribution
    revenue_attribution.run()


def run_specwriter():
    """Each app self-writes SPEC.md from merged outcomes + usage (compounding plan quality)."""
    import spec_writer
    spec_writer.run()


def run_autoexec():
    """Auto-run the safe majority of proven operator steps (no click), plus execute queued ones."""
    import action_runner
    action_runner.auto_execute()
    action_runner.run()


def run_draftactions():
    """Pre-generate exact command/steps for each operator/credential to-do (review + run one line)."""
    import action_drafter
    action_drafter.run()


def run_prebrief():
    """Attach a plain-English legal decision brief to each legal card."""
    import legal_prebrief
    legal_prebrief.run()


def run_bizradar():
    """Flag queued work that would change pricing/data-use/regulatory posture as an early decision."""
    import business_radar
    business_radar.run()


def run_actionexec():
    """Execute ONLY the safe, you-clicked operator steps queued from the cockpit."""
    import action_runner
    action_runner.run()


def run_mergetrain():
    """Batch non-overlapping judge-passed branches into one green CI run and merge the train."""
    import merge_train
    merge_train.run()


def run_forecast():
    """Project end-of-day spend from burn rate; pause on real-$ runaway, alert on notional spike."""
    import spend_forecast
    spend_forecast.run()


def run_arbitrage():
    """Rebalance provider routing to the cheapest capable frontier as prices/quality move."""
    import price_arbitrage
    price_arbitrage.run()


def run_autoscale():
    """Emit scale up/down signal when weighted demand diverges from live fleet capacity."""
    import autoscale_signal
    autoscale_signal.run()


def run_learnmerges():
    """Reinforcement from shipped work: distill merged diffs into conventions + regression rules."""
    import learn_from_merges
    learn_from_merges.run()


def run_dedup():
    """Collapse near-duplicate queued tasks so the swarm solves each thing once."""
    import task_dedup
    task_dedup.apply()


def run_canaryecon():
    """Promote/rollback canaries on live production cost + quality."""
    import canary_economics
    canary_economics.run()


def run_billingguard():
    """Tripwire: pause everything if any real API spend or leaked key appears (anti-$500-invoice)."""
    import billing_guard
    billing_guard.run()


def run_governor():
    """Allocate fleet capacity across apps by expected value (ROI x success / cost)."""
    import portfolio_governor
    portfolio_governor.run(apply=True)


def run_costslo():
    """Hold each app's $/merge SLO by biasing routing cheaper; escalate on hard breach."""
    import cost_slo
    cost_slo.run(apply=True)


def run_promote():
    """Propose productizing capabilities proven across multiple apps."""
    import capability_promote
    capability_promote.run(apply=True)


def run_prewarm():
    """Pre-create worktrees + warm context for the next claimable tasks (zero claim latency)."""
    import prewarm
    prewarm.run()


def run_appreview():
    """Perpetual cross-app AI/API triage review: rate cost/quality, learn cheapest good route."""
    import app_triage_review
    app_triage_review.run()


def run_preflight():
    """Cheap-model triage for queued tasks before spending agentic coder time."""
    import preflight_gate
    preflight_gate.run()


def run_cluster():
    """Cluster pending approval cards so the human can bulk-approve siblings."""
    import approval_cluster
    approval_cluster.tag()


def run_conventions():
    """Refresh each repo's CLAUDE.md (compounding caching + on-style, cheaper builds)."""
    import synthesize_conventions
    for p in db.select("projects", {"select": "name,repo_path"}) or []:
        repo = p.get("repo_path", "")
        if repo and os.path.isdir(repo):
            try:
                synthesize_conventions.run(repo)
            except Exception as e:
                print(f"conventions {p.get('name')}: {e}")


def run_roi():
    import roi
    report = roi.report()
    if not report:
        return
    max_cpm = max((r["cost_per_merge"] or 0) for r in report if r["cost_per_merge"]) or 1
    for r in report:
        cpm = r["cost_per_merge"]
        if cpm is None:
            weight = 1
        elif cpm <= max_cpm * 0.25:
            weight = 3  # high-ROI: more concurrency
        elif cpm <= max_cpm * 0.6:
            weight = 2
        else:
            weight = 1  # low-ROI: baseline only
        rows = db.select("projects", {"select": "id", "name": f"eq.{r['project']}"}) or []
        if rows:
            db.update("projects", {"id": rows[0]["id"]}, {"concurrency_weight": weight})
        print(f"roi {r['project']}: cpm=${cpm} weight={weight}")


JOBS = {
    "spec": run_spec,
    "chaos": run_chaos,
    "txn": run_txn,
    "scout": run_scout,
    "deploy": run_deploy,
    "roi": run_roi,
    "batch": run_batch,
    "unstick": run_unstick,
    "dagfix": run_dagfix,
    "selftune": run_selftune,
    "batchmech": run_batchmech,
    "appreview": run_appreview,
    "cluster": run_cluster,
    "conventions": run_conventions,
    "governor": run_governor,
    "costslo": run_costslo,
    "promote": run_promote,
    "prewarm": run_prewarm,
    "billingguard": run_billingguard,
    "learnmerges": run_learnmerges,
    "dedup": run_dedup,
    "canaryecon": run_canaryecon,
    "forecast": run_forecast,
    "arbitrage": run_arbitrage,
    "autoscale": run_autoscale,
    "mergetrain": run_mergetrain,
    "draftactions": run_draftactions,
    "prebrief": run_prebrief,
    "bizradar": run_bizradar,
    "actionexec": run_actionexec,
    "legaltriage": run_legaltriage,
    "decisionbriefs": run_decisionbriefs,
    "improve": run_improve,
    "improvemeasure": run_improvemeasure,
    "committees": run_committees,
    "committeecal": run_committeecal,
    "committeedocket": run_committeedocket,
    "committeedigest": run_committeedigest,
    "committeerollout": run_committeerollout,
    "committeeboard": run_committeeboard,
    "committeewatch": run_committeewatch,
    "committeeminutes": run_committeeminutes,
    "committeekg": run_committeekg,
    "committeemeta": run_committeemeta,
    "remediate": run_remediate,
    "selfcheck": run_selfcheck,
    "objective": run_objective,
    "revattr": run_revattr,
    "specwriter": run_specwriter,
    "autoexec": run_autoexec,
    "pushdecisions": run_pushdecisions,
    "roadmap": run_roadmap,
    "selfheal": run_selfheal,
    "newapp": run_newapp,
    "autopilot": run_autopilot,
    "abedge": run_abedge,
    "stripe": run_stripe,
    "ownerreport": run_ownerreport,
    "worktreegc": run_worktreegc,
    "releasetrain": run_releasetrain,
    "deployverify": run_deployverify,
    "preflight": run_preflight,
}

if __name__ == "__main__":
    job = sys.argv[1] if len(sys.argv) > 1 else "help"
    if job not in JOBS:
        print(f"usage: periodic.py {'|'.join(JOBS)}")
        sys.exit(1)
    # honor the kill switch: model-spending jobs don't run while paused.
    # these only read outcomes / move task state / edit thresholds — they never spend tokens
    _SAFE_WHEN_PAUSED = {"roi", "txn", "unstick", "dagfix", "selftune", "batchmech"}
    if job not in _SAFE_WHEN_PAUSED:
        try:
            import kill_switch
            if kill_switch.is_paused():
                print(f"periodic {job}: skipped (paused)")
                sys.exit(0)
        except Exception:
            pass
    JOBS[job]()
