PROJECT: beethoven

- id: contracts-madeus-development-session-fabric
  title: Pin the canonical development-session, event, proof, lease, and steering contracts
  material: yes
  model: opus
  depends: []
  proof: python3 -m unittest runner.tests.test_development_session_contract -v
  prompt: |
    Extend the orchestrator rather than creating a parallel pipeline. Define versioned contracts for one portfolio-wide development session fabric shared by Codex/ChatGPT, Claude Cowork, orchestrator-native coders, and thin product-app clients. File scope: add a focused runner/development_session_contract.py, its tests, and an additive Supabase migration only. Pin states CREATED, PLANNING, PLAN_REVIEW, EXECUTING, VERIFYING, INTEGRATING, RELEASING, DEPLOYED_AND_VERIFIED, BLOCKED; append-only sequenced events; exact base/artifact/release SHAs; runner identity/generation; lease fencing token; proof receipts; steering decisions; adapter identity; and schema/version compatibility. Define DONE and MERGED as non-production states. Include rollback and backward-compatible rollout rules. Do not implement adapters or UI here.

- id: canonical-proof-ledger-and-operator-projection
  title: Make every operator-visible state a projection of durable delivery evidence
  material: yes
  model: sonnet
  depends: [contracts-madeus-development-session-fabric]
  proof: python3 -m unittest runner.tests.test_canonical_proof_ledger -v && cd web && npx vitest run server/utils/proofProjection.test.ts
  prompt: |
    Extend task_artifacts, releases, release_manifest, deployment_terminal, shipped_metrics, the orchestrator snapshot API, and proof UI through a single proof projection. File scope: runner/canonical_proof_ledger.py, focused extensions to existing proof/release modules, one migration if needed, web/server/utils/proofProjection.ts, snapshot/API/UI consumers, and tests. Every pass must link to its receipt; unknown evidence must display UNKNOWN/PENDING, never PASS. MERGED proves only integration reachability. DEPLOYED_AND_VERIFIED requires exact live release SHA plus task-defined production journey receipt. Paginate all ledger reads. Add regression fixtures for phantom MERGED, missing artifact, stale release, and evidence beyond PostgREST row 1000.

- id: runner-generation-admission-and-write-fencing
  title: Fence stale Macs with runner generations and runtime-contract admission
  material: yes
  model: opus
  depends: [contracts-madeus-development-session-fabric]
  proof: python3 -m unittest runner.tests.test_runner_generation_fencing -v
  prompt: |
    Extend runtime_contract.py, fleet heartbeats, claim_task, paused_host_guard, stale_host_guard, and DB migrations. Introduce immutable runner_id plus monotonic runner_generation and a control-plane admitted generation/contract digest. Every claim and canonical mutation must carry runner_id, generation, code_sha, contract_hash, and fencing token; stale or unadmitted generations may finish producing a recoverable artifact but may not claim, integrate, release, or mutate canonical proof. Automatically drain contract-mismatched hosts and emit durable alerts in a separate successful transaction. Preserve block-start/allow-safe-finish semantics. Include two-Mac race, restart, rollout, missing-field compatibility, and stale-writer tests.

- id: repository-integration-and-release-owner-leases
  title: Enforce one fenced integrator and releaser per repository
  material: yes
  model: sonnet
  depends: [contracts-madeus-development-session-fabric, runner-generation-admission-and-write-fencing]
  proof: python3 -m unittest runner.tests.test_repository_delivery_leases -v
  prompt: |
    Extend integration_owner.py, merge_train.py, release_train.py, deployment_terminal.py, and related migrations. Replace hostname preference with renewable DB leases scoped by repository and role (integrator/releaser), bound to runner generation and a monotonically increasing fencing token. Verify the token on every integration branch update, push, release row, manifest, and production promotion. A timed-out predecessor must be unable to write after takeover. Remove anonymous release writes after a measured compatibility window. Add concurrent two-Mac, lease-expiry, clock-skew, retry, and takeover tests without deleting in-flight artifacts.

- id: durable-development-session-event-and-artifact-store
  title: Persist resumable session events and artifacts across every Mac and cloud adapter
  material: yes
  model: sonnet
  depends: [contracts-madeus-development-session-fabric]
  proof: python3 -m unittest runner.tests.test_development_session_store -v
  prompt: |
    Extend the existing task_artifacts and database fabric with development_sessions, development_session_events, and durable artifact references. File scope: one additive migration, runner/development_session_store.py, and tests. Events must be append-only with per-session sequence/idempotency keys and cursor pagination; artifacts must record digest, media type, producing adapter/runner/generation, task, commit, and durable location. Release-critical writes must never silently fall back to Mac-local JSON. Provide resume/replay APIs, retention policy, safe redaction, and compatibility import for existing task_artifacts. Test concurrent append, duplicate delivery, cursor replay, host loss, and >1000 events.

- id: runner-backed-development-session-broker
  title: Broker trusted worktree sessions for Codex, Cowork, and native executors
  material: yes
  model: opus
  depends: [contracts-madeus-development-session-fabric, runner-generation-admission-and-write-fencing, durable-development-session-event-and-artifact-store]
  proof: python3 -m unittest runner.tests.test_development_session_broker -v
  prompt: |
    Build runner/development_session_broker.py as the only execution broker. Extend existing worktree, model gateway, agentic coder, Cowork, and Codex CLI/app-server integration points; do not execute repository tools inside Vercel. Adapters must implement capability discovery, start/steer/cancel/resume, streamed event capture, tool approval, bounded permissions, cost/model telemetry, and final artifact receipt. Pin every session to an exact repo/base SHA and isolated worktree. Add fake adapters for deterministic tests covering disconnect/resume, duplicated events, cancellation, approval hold, and artifact recovery. Vercel remains intake/status only.

- id: frontier-batch-planning-council
  title: Add risk-gated frontier multi-vendor planning and adversarial synthesis
  material: yes
  model: opus
  depends: [contracts-madeus-development-session-fabric]
  proof: python3 -m unittest runner.tests.test_frontier_planning_council -v
  prompt: |
    Extend planner.py, plan_stage.py, committees.py, model_catalog.py, model_policy.py, and context assembly. For broad/high-value/material objectives, build one pinned codebase dossier at an exact base SHA (repository/symbol graph, relevant files, history, invariants, failures, release evidence) and give independently selected frontier provider families tool-enabled retrieval against it. Produce independent proposals, anonymized cross-critiques, a risk adversary review, and a separate synthesizing judge. Persist the complete council evidence and one signed implementation contract containing non-goals, file ownership, DAG, migrations/rollback, tests, journey probes, budgets, and escalation rules. Capability-probe actual provider/model availability; never trust catalog strings alone. Skip council overhead for small/mechanical work and test deterministic fallback.

- id: signed-plan-economic-execution-router
  title: Route economical implementers against a signed plan without losing quality gates
  material: no
  model: sonnet
  depends: [contracts-madeus-development-session-fabric, frontier-batch-planning-council, runner-backed-development-session-broker]
  proof: python3 -m unittest runner.tests.test_signed_plan_execution_router -v
  prompt: |
    Extend plan_stage, tier_router, agentic_coders, task slicing, model routing, and QA integration so the frontier council owns high-value planning while economical available models implement small non-overlapping worktree slices. Executors may not silently change contract boundaries; evidence-driven uncertainty escalates to targeted replanning. Record planned versus actual files, model/provider/cost, tests, and deviations. Require independent reviewer families for broad/security/legal/material changes. Add tests for cheap-route selection, unavailable providers, plan deviation, overlapping file scopes, escalation, and cost-per-DEPLOYED_AND_VERIFIED accounting.

- id: foulkon-illuminati-apparently-steering-hooks
  title: Embed signed steering decisions at plan, tool, merge, and release boundaries
  material: yes
  model: opus
  depends: [contracts-madeus-development-session-fabric, runner-backed-development-session-broker]
  proof: python3 -m unittest runner.tests.test_development_steering_hooks -v
  prompt: |
    Extend the existing Darwin/Foulkon governance kernel, Illuminati risk logic, Apparently legal capability, approval policy, and broker hooks. Implement versioned allow/warn/hold steering decisions before planning approval, consequential tool calls, integration, and release. Each receipt must include rule/authority, rationale, risk, alternatives, scope, digest, latency, and authorized override. Apparently contributes only where legal/domain relevance is established; Illuminati/Foulkon handles general risk. Never hide model prose as policy. Cache low-risk deterministic decisions, redact secrets, and provide safe failure behavior. Test enforcement, override audit, cross-project isolation, irrelevant-legal bypass, and sub-100ms cached policy evaluation.

- id: shared-development-terminal-sdk-and-madeus-client
  title: Replace terminal facades with one streamed, proof-backed client SDK
  material: yes
  model: sonnet
  depends: [contracts-madeus-development-session-fabric, canonical-proof-ledger-and-operator-projection, durable-development-session-event-and-artifact-store, runner-backed-development-session-broker, foulkon-illuminati-apparently-steering-hooks]
  proof: cd web && npx vitest run server/utils/developmentSessionClient.test.ts components/DevelopmentTerminal.test.ts
  prompt: |
    Build a shared TypeScript development-session client in the orchestrator web app and make Madeus its reference UI. Use authenticated intake plus durable SSE/WebSocket/realtime cursor replay from the broker; never run shell/filesystem/raw service-role SQL in Vercel. Show session state, host/generation/adapter, plan and steering receipts, streamed stdout/stderr/tool actions, worktree/branch/diff/commit, test artifacts, integration proof, release SHA/URL, and production journey. Reconnect without losing output. UNKNOWN must remain unknown; remove demo/fabricated passes. Add auth, pagination, disconnect/resume, accessibility, and proof-projection tests.

- id: task-defined-production-journey-receipts
  title: Require feature-level production journeys in addition to HTTP and SHA checks
  material: yes
  model: sonnet
  depends: [contracts-madeus-development-session-fabric, canonical-proof-ledger-and-operator-projection, repository-integration-and-release-owner-leases]
  proof: python3 -m unittest runner.tests.test_production_journey_receipts -v
  prompt: |
    Extend deploy_verify.py, deployment_terminal.py, release_manifest.py, task artifacts, and proof UI. Each task or fused release must declare a bounded production journey probe appropriate to its change; exact release SHA plus base health remains necessary but is not sufficient. Execute journeys after deployment, store structured redacted receipts with URL/environment/SHA/steps/assertions/timing, and promote only attributed tasks whose required journeys pass. Handle non-web changes with explicit alternate probes. Add retry/backoff, flaky classification, rollback/backpressure behavior, and regression tests proving HTTP 200 alone cannot promote a task.

- id: complete-scan-window-truth-remediation
  title: Eliminate remaining unordered bounded scans from identity and delivery paths
  material: no
  model: sonnet
  depends: [contracts-madeus-development-session-fabric]
  proof: python3 -m unittest runner.tests.test_scan_window_contracts -v
  prompt: |
    Continue the documented scan-window audit across runner and web. Inventory every remaining bounded/unordered PostgREST read used for identity, dedupe, dependency resolution, committees, configuration, artifacts, sessions, merge/release truth, and dashboards. Replace identity-set scans with select_all/keyset pagination or server-side exact/RPC operations; make intentionally recent-window queries explicitly ordered and named. Add fixtures beyond row 1000 and a static regression test that prevents new unsafe scan shapes in critical modules. Do not mechanically paginate legitimate top-N analytics without documenting semantics.

- id: development-fabric-observability-slos-and-rollout
  title: Operate the session fabric by verified-delivery SLOs and staged rollout
  material: yes
  model: sonnet
  depends: [contracts-madeus-development-session-fabric, canonical-proof-ledger-and-operator-projection, runner-generation-admission-and-write-fencing, repository-integration-and-release-owner-leases, runner-backed-development-session-broker, frontier-batch-planning-council, shared-development-terminal-sdk-and-madeus-client, task-defined-production-journey-receipts, complete-scan-window-truth-remediation]
  proof: python3 -m unittest runner.tests.test_development_fabric_slos -v && cd web && npx vitest run server/utils/developmentFabricSlo.test.ts
  prompt: |
    Add fleet/session/delivery observability and a reversible rollout plan. Measure production-verified improvements/day, p50/p95 objective-to-DEPLOYED_AND_VERIFIED time, false-shipped rate, phantom rate, recovery rate, queue age, host-generation drift, session reconnect loss, cost per verified change, and journey reliability. Create one operator view and alert thresholds with project/host/session drill-down. Roll out shadow-read projections first, then one canary repo/Mac, then adapters and product embeds; include rollback switches and a zero-fabricated-proof invariant. Do not optimize raw task counts.

PROJECT: apparently

- id: contracts-apparently-development-session-embed
  title: Pin Apparently context and legal-steering boundaries for the shared terminal
  material: no
  model: sonnet
  depends: [beethoven:shared-development-terminal-sdk-and-madeus-client, beethoven:foulkon-illuminati-apparently-steering-hooks]
  proof: the Apparently adapter contract test passes and no direct serverless execution endpoint is introduced
  prompt: |
    Define the Apparently-side adapter contract for the shared Madeus development-session client: repository/project identity, scoped authentication, legal-context contribution, steering display, deep links, and allowed proof fields. File scope must be limited to a small contract module and tests; do not implement the UI here and do not duplicate the broker.

- id: adopt-shared-development-terminal-in-apparently
  title: Replace Apparently's copied terminal facade with the shared session client
  material: no
  model: sonnet
  depends: [contracts-apparently-development-session-embed, beethoven:shared-development-terminal-sdk-and-madeus-client]
  proof: Apparently typecheck/unit/e2e suites pass and a session reconnect test preserves ordered output and proof links
  prompt: |
    Replace the copied DevelopmentTerminal and missing /api/terminal/execute assumption with the shared client. Preserve Apparently visual conventions while showing real streamed events, legal steering, diff/test/merge/release/journey receipts, and truthful unknown states. Add scoped auth and reconnect tests. Never expose repository tools or service-role SQL from the deployed web runtime.

PROJECT: tomorrow

- id: contracts-tomorrow-development-session-embed
  title: Pin Tomorrow project context for the shared terminal
  material: no
  model: sonnet
  depends: [beethoven:shared-development-terminal-sdk-and-madeus-client]
  proof: the Tomorrow adapter contract test passes and all session requests remain project-scoped
  prompt: |
    Define the Tomorrow-side shared terminal adapter contract, including project identity, authentication, app-specific deep links, proof fields, and steering presentation. Limit scope to the adapter contract and tests; do not clone the broker or execution APIs.

- id: adopt-shared-development-terminal-in-tomorrow
  title: Replace Tomorrow's nonfunctional terminal clone with the shared session client
  material: no
  model: sonnet
  depends: [contracts-tomorrow-development-session-embed, beethoven:shared-development-terminal-sdk-and-madeus-client]
  proof: Tomorrow typecheck/unit/e2e suites pass and a real session state is rendered without fabricated demo data
  prompt: |
    Replace Tomorrow's copied DevelopmentTerminal and missing execution endpoint with the shared session client. Preserve styling, add authenticated project-scoped intake and streamed reconnectable events, and render the common plan/steering/diff/test/integration/release/journey proof surface. Add regression tests for offline, unknown, blocked, merged-only, and deployed-and-verified states.

PROJECT: pareto-2080

- id: contracts-pareto-development-session-embed
  title: Pin Pareto project and financial-risk steering boundaries for the shared terminal
  material: yes
  model: sonnet
  depends: [beethoven:shared-development-terminal-sdk-and-madeus-client, beethoven:foulkon-illuminati-apparently-steering-hooks]
  proof: the Pareto adapter contract test passes and financial/legal context cannot broaden execution permissions
  prompt: |
    Define Pareto's shared terminal adapter contract with project identity, scoped auth, financial/legal steering context, proof presentation, and explicit separation between advice/governance and repository execution authority. Limit implementation to contract and tests.

- id: adopt-shared-development-terminal-in-pareto
  title: Replace Pareto's terminal clone with the shared session client
  material: yes
  model: sonnet
  depends: [contracts-pareto-development-session-embed, beethoven:shared-development-terminal-sdk-and-madeus-client]
  proof: Pareto typecheck/unit/e2e suites pass and custody-sensitive actions produce visible steering holds before execution
  prompt: |
    Replace Pareto's copied/nonfunctional terminal with the shared session client. Preserve product styling, add reconnectable event streaming and exact proof links, and display Foulkon/Illuminati/Apparently decisions for custody-sensitive work without granting those advisers shell authority. Remove fabricated success states and add auth, steering-hold, merged-only, and production-journey tests.

PROJECT: illuminati

- id: contracts-illuminati-development-session-embed
  title: Pin Illuminati steering-adapter and session-display boundaries
  material: yes
  model: opus
  depends: [beethoven:shared-development-terminal-sdk-and-madeus-client, beethoven:foulkon-illuminati-apparently-steering-hooks]
  proof: the Illuminati adapter contract tests pass and risk guidance is a signed receipt rather than executable authority
  prompt: |
    Define Illuminati's two bounded roles: a signed risk-steering adapter into the shared broker and a thin project-scoped terminal client. Specify auth, decision schema/version, latency, fallback, override audit, proof display, and strict separation from shell/release authority. Limit scope to contracts and tests.

- id: adopt-shared-development-terminal-in-illuminati
  title: Replace missing WebSocket and demo fallback with the shared session client
  material: yes
  model: sonnet
  depends: [contracts-illuminati-development-session-embed, beethoven:shared-development-terminal-sdk-and-madeus-client]
  proof: Illuminati typecheck/unit/e2e suites pass; disconnect never loads demo agents or deployments in production
  prompt: |
    Remove the nonexistent /api/terminal/ws loop, demo-state production fallback, and fake cascade responses. Adopt the shared authenticated session client with cursor replay and explicit UNKNOWN/OFFLINE states. Render real steering decisions and proof receipts. Add tests for connection failure, resume, duplicate event suppression, signed decision display, and absence of demo data outside fixtures.

PROJECT: apparently-law

- id: contracts-apparently-law-development-session-embed
  title: Pin Tomorrow Law/Apparently Law legal-context boundaries for the shared terminal
  material: yes
  model: opus
  depends: [beethoven:shared-development-terminal-sdk-and-madeus-client, beethoven:foulkon-illuminati-apparently-steering-hooks]
  proof: the Apparently Law adapter contract tests pass and privileged/legal context is redacted and scope-limited
  prompt: |
    Define the Apparently Law/Tomorrow Law shared terminal adapter with project identity, scoped authentication, privileged-data redaction, legal steering contribution, evidence links, and override policy. Legal analysis may advise or hold governed actions but may not inherit repository execution credentials. Limit scope to contracts and tests.

- id: adopt-shared-development-terminal-in-apparently-law
  title: Add the proof-backed shared development terminal to Apparently Law/Tomorrow Law
  material: yes
  model: sonnet
  depends: [contracts-apparently-law-development-session-embed, beethoven:shared-development-terminal-sdk-and-madeus-client]
  proof: Apparently Law typecheck/unit/e2e suites pass with privileged-data redaction, reconnect, steering, and production-proof cases
  prompt: |
    Integrate the shared terminal client as a project-scoped development surface. Show real plan, streamed work, steering, diff/test/integration/release/journey evidence while redacting privileged or secret content. Add reconnect, access-control, redaction, hold/override, merged-only, and deployed-and-verified tests. Do not create a product-local coding engine.
