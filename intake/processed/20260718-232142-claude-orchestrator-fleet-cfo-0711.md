PROJECT: claude-orchestrator

# Fleet CFO — a PORTFOLIO capital allocator. Verified gap: per-task model routing (bandit.py/model_router.py) +
# per-task cost (cost_ledger.py) + EV-gated BUILD roadmap exist, but nothing allocates the cost-capped compute/agent
# budget ACROSS products by portfolio EV x strategic value x risk. Self-executable by the fleet (runner lane).
# GOVERNANCE: the allocator PROPOSES; the owner approves (same pattern as relfix-autonomous-roadmap — cards await
# approval in the dashboard). It must NOT silently change spend. Additive; fail-soft (never wedge the runner).

- id: fleet-cfo-allocator
  title: Portfolio capital allocator — propose budget/compute splits across apps by EV x strategy x risk
  material: yes
  model: opus
  depends: []
  proof: `python3 -m pytest runner/tests -q -k allocator` exits 0
  prompt: |
    Add runner/capital_allocator.py: a pure, fail-soft allocator that reads recent outcomes + spend (cost_ledger.py,
    outcomes table via the existing DB helpers) and each app's strategic weight + risk posture (from fleet_config /
    a new ORCH_APP_STRATEGY_WEIGHTS key), and PROPOSES a budget/concurrency split across the registered projects that
    maximizes portfolio EV per dollar subject to per-app floors/ceilings and the global cost cap. It returns a proposal
    object (per-app: current vs proposed budget, expected EV delta, rationale) — it does NOT mutate fleet_config.
    Wire it to emit an approval card (reuse the existing approval-card path used by relfix-autonomous-roadmap) so the
    owner arms it. Env-configurable (ORCH_* keys), thread-safe, fail-soft (any error -> no proposal, never wedge the
    runner). Add runner/tests/test_capital_allocator.py covering: EV-ranked proposal respects floors/ceilings + global
    cap; a starved high-EV app is proposed more; errors degrade to an empty proposal. Do not touch model routing here.

- id: fleet-cfo-dashboard
  title: Fleet-CFO dashboard surface — portfolio allocation view + one-click approve (5/95)
  material: no
  model: sonnet
  depends: [fleet-cfo-allocator]
  proof: `cd web && npx nuxi typecheck` exits 0 (or `npm run build` exits 0 if typecheck unavailable)
  prompt: |
    Add a Fleet-CFO panel to the Nuxt+Tailwind dashboard (web/) that renders the allocator's proposal as the OS's 5/95
    pattern: the recommended allocation shown as the Outcome (fact), a single Recommended one-click "apply split"
    (which writes fleet_config only on owner approval), and a "see the math" reveal exposing per-app EV, spend, and
    rationale (the proof). Reuse existing dashboard components, the approval-queue styling, and design tokens; add a
    sidebar + command-palette entry consistent with the other lanes. Realtime where the board already is; no new poll
    loops (respect relfix-db-poll-diet). Display-only until the owner approves an apply.

OPERATOR:
  - Set ORCH_APP_STRATEGY_WEIGHTS (per-app strategic weight) + per-app budget floors/ceilings in fleet_config before arming auto-proposals.
  - The allocator only proposes; applying a split is an owner action in the dashboard. Keep it proposal-only until you've reviewed a few cards.
