PROJECT: beethoven

# Portfolio command-terminal + cross-app optimization batch (2026-07-08).
# Goal: make the orchestrator the primary coding control surface, keep the backlog draining,
# and ensure improvements in one app are safely converted into reusable capabilities for the
# others. Public/user-facing copy must describe value at a general level and must not expose
# internal routing, proprietary methods, or protected legal/product strategy.

- id: terminal-provider-command-center
  title: Make the dashboard the primary coding terminal for portfolio work
  material: no
  model: sonnet
  depends: []
  proof: `cd web && npm run build` exits 0
  prompt: |
    Extend the orchestrator dashboard so future coding work can be initiated, routed, monitored,
    repaired, merged, and deployment-verified from the orchestrator instead of direct VS Code,
    Claude Code, Codex, Gemini, DeepSeek, or Ollama sessions. Preserve the existing dashboard
    style and auth patterns. Required controls: priority portfolio vs single-project target;
    route profile (value-first, tournament, subscription/max-covered, local-sensitive, fast lane);
    sensitivity profile; mode (implement, optimize, remediate, propagate, canary); quick objective
    templates; provider/model evidence status; and a task composer that inserts queue rows with
    route/sensitivity/mode metadata. Queue insertions must surface errors. Every generated prompt
    must instruct agentic coders to resolve build/test/integration/deploy failures inside the
    implementation loop and avoid requeueing unless a missing secret or operator sign-off is truly
    required.

- id: cross-app-critical-feature-map
  title: Map and cross-optimize critical functions across every portfolio app
  material: yes
  model: opus
  depends: []
  proof: `python3 -m pytest runner/tests -q` exits 0
  prompt: |
    Build a portfolio feature map that captures, for Tomorrow, Apparently, Smarter, Hisanta,
    Galop, Pareto/2080, and the orchestrator, the critical surfaces that must be continuously
    reviewed: deliberation/CADE, negotiation rooms, app optimization loops, contract generation,
    IOI relationships and matching, licensing/registration intake, owner/controller/employee
    data collection, memo/RLO review, project coordination, email ingestion/sorting, temperament
    and collaboration scoring, cybersecurity, design/UI/UX, deployment health, and shared proof
    packs. Store it as machine-readable config in the orchestrator, with per-surface owner app,
    reusable capability candidates, proof command, privacy tier, and propagation eligibility.
    Add tests that validate schema shape, project coverage, privacy-tier presence, and that unknown
    apps degrade without blocking the runner.

- id: autonomous-backlog-drain-loop
  title: Keep the improvement backlog draining without human nudges
  material: no
  model: sonnet
  depends: [cross-app-critical-feature-map]
  proof: `python3 -m pytest runner/tests -q` exits 0
  prompt: |
    Add an autonomous drain coordinator that continuously prefers high-value recovery, release-fix,
    and already-mostly-solved tasks before net-new work until the blocked/retry/missing-branch
    backlog is gone. It should use the feature map, thermal score, dependency prewarm status,
    patch-template cache, and merge-train pressure to choose next work. Important: when a task
    fails build/test/integration/deploy, keep the same agentic implementation loop responsible
    for the fix when possible instead of repeatedly requeueing generic buffer tasks. Record exact
    counters in the dashboard/autopilot logs: queued, running, retry, blocked-like, recovered,
    merged, deployed, and tasks avoided by reuse/cache.

- id: qa-public-copy-privacy-gate
  title: Add QA layer for protected public-facing copy
  material: yes
  model: sonnet
  depends: [cross-app-critical-feature-map]
  proof: `python3 -m pytest runner/tests -q` exits 0
  prompt: |
    Add a QA gate that scans changed public-facing pages/components across portfolio apps and
    flags copy that exposes internal routing details, private methods, protected strategy,
    privileged legal posture, secrets, or implementation mechanics. The gate should allow high-level
    value statements and user-benefit positioning. Integrate it into the orchestrator proof-pack
    path so every deployment candidate records copy/privacy status. Include allowlist and denylist
    tests, and make remediation a normal task patch rather than a manual blocker whenever text can
    be safely generalized.

PROJECT: tomorrow

- id: tomorrow-otc-command-mesh-uplift
  title: Improve OTC exchange contract, IOI, matching, and negotiation mesh
  material: yes
  model: opus
  depends: []
  proof: `npm test` or the repo's existing build/test command exits 0
  prompt: |
    Review and improve Tomorrow's OTC exchange critical flows: contract generation, IOI relationship
    graph, matching quality, negotiation/war-room mechanics, counterparty review, settlement proof
    packs, and bot collaboration. Borrow from the orchestrator's provider/model tournament pattern:
    distinct planner, drafter, verifier, red-team, and judge roles compete by proof quality and
    accepted outcome cost. Borrow back anything Tomorrow does better into reusable shared-brain
    recipes. Keep outbound user/public copy high-level; do not expose internal strategy or exact
    decision mechanics. Implement concrete fixes and tests, not a report-only review.

PROJECT: apparently

- id: apparently-cade-registration-licensing-uplift
  title: Improve CADE, licensing, registration, intake, memo, and RLO review flows
  material: yes
  model: opus
  depends: []
  proof: `npm test` or the repo's existing build/test command exits 0
  prompt: |
    Review and improve Apparently's CADE structure and critical operational flows: licensing and
    registration workflow, owner/controller/employee data collection, memo drafting, RLO review,
    audit trail, evidence/proof packs, and reusable precedent/capability capture. Use the shared
    orchestrator mesh pattern: separate roles for intake, draft, review, verification, and red-team,
    with proofs recorded before promotion. Generalize any successful CADE mechanics back into the
    shared capability library for Tomorrow, Smarter, and the orchestrator. Keep user-facing copy
    abstract and product-value oriented.

PROJECT: smarter

- id: smarter-work-os-email-negotiation-uplift
  title: Improve Smarter autonomous work OS, email, negotiation, and learning loops
  material: yes
  model: opus
  depends: []
  proof: `npm test` or the repo's existing build/test command exits 0
  prompt: |
    Review and improve Smarter's project-management coordination, autonomous user-task learning,
    process replication into Apparently, email ingestion/sorting, negotiation room, coworker
    temperament/sociability/problem-pattern scoring, human approval boundaries, and proof packs.
    Implement concrete improvements with tests and safe data boundaries. Capture reusable pieces
    as shared-brain recipes that can be deployed to Apparently, Tomorrow, and the orchestrator.
    Keep outward-facing explanations high-level and avoid exposing internal methods or strategy.

PROJECT: hisanta

- id: hisanta-critical-flow-security-design-uplift
  title: Improve Hisanta critical flows, security, and reusable UX patterns
  material: yes
  model: sonnet
  depends: []
  proof: `npm test` or the repo's existing build/test command exits 0
  prompt: |
    Review and improve Hisanta's critical user flows, auth/data boundaries, deployment health,
    design/UI consistency, and reusable platform patterns. Pull proven shared components from the
    orchestrator capability library where appropriate, add tests, and record reusable artifacts back
    into the portfolio proof/capability system.

PROJECT: galop

- id: galop-critical-flow-security-design-uplift
  title: Improve Galop critical flows, security, and reusable UX patterns
  material: yes
  model: sonnet
  depends: []
  proof: `npm test` or the repo's existing build/test command exits 0
  prompt: |
    Review and improve Galop's critical user flows, auth/data boundaries, deployment health,
    design/UI consistency, vendor seam safety, and reusable platform patterns. Pull proven shared
    components from the orchestrator capability library where appropriate, add tests, and record
    reusable artifacts back into the portfolio proof/capability system.

PROJECT: pareto-2080

- id: pareto-critical-flow-security-design-uplift
  title: Improve Pareto/2080 critical flows, security, and reusable UX patterns
  material: yes
  model: sonnet
  depends: []
  proof: `npm test` or the repo's existing build/test command exits 0
  prompt: |
    Review and improve Pareto/2080's critical user flows, auth/data boundaries, deployment health,
    design/UI consistency, proof-pack usefulness, and reusable platform patterns. Pull proven shared
    components from the orchestrator capability library where appropriate, add tests, and record
    reusable artifacts back into the portfolio proof/capability system.

OPERATOR:
  - Confirm real external credentials, filings, money movement, customer-facing legal/regulatory actions, and production secrets outside the code loop before enabling any live action path.
