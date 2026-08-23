PROJECT: apparently

- id: contracts-apparently-development-session-embed
  title: Pin Apparently context and legal-steering boundaries for the shared terminal
  material: no
  model: sonnet
  submitted-by: Codex operator-directed orchestrator remediation
  depends: [beethoven:shared-development-terminal-sdk-and-madeus-client, beethoven:foulkon-illuminati-apparently-steering-hooks]
  proof: the Apparently adapter contract test passes and no direct serverless execution endpoint is introduced
  prompt: |
    Define the Apparently-side adapter contract for the shared Madeus development-session client: repository/project identity, scoped authentication, legal-context contribution, steering display, deep links, and allowed proof fields. File scope must be limited to a small contract module and tests; do not implement the UI here and do not duplicate the broker.

- id: adopt-shared-development-terminal-in-apparently
  title: Replace Apparently's copied terminal facade with the shared session client
  material: no
  model: sonnet
  submitted-by: Codex operator-directed orchestrator remediation
  depends: [contracts-apparently-development-session-embed, beethoven:shared-development-terminal-sdk-and-madeus-client]
  proof: Apparently typecheck/unit/e2e suites pass and a session reconnect test preserves ordered output and proof links
  prompt: |
    Replace the copied DevelopmentTerminal and missing /api/terminal/execute assumption with the shared client. Preserve Apparently visual conventions while showing real streamed events, legal steering, diff/test/merge/release/journey receipts, and truthful unknown states. Add scoped auth and reconnect tests. Never expose repository tools or service-role SQL from the deployed web runtime.

PROJECT: tomorrow

- id: contracts-tomorrow-development-session-embed
  title: Pin Tomorrow project context for the shared terminal
  material: no
  model: sonnet
  submitted-by: Codex operator-directed orchestrator remediation
  depends: [beethoven:shared-development-terminal-sdk-and-madeus-client]
  proof: the Tomorrow adapter contract test passes and all session requests remain project-scoped
  prompt: |
    Define the Tomorrow-side shared terminal adapter contract, including project identity, authentication, app-specific deep links, proof fields, and steering presentation. Limit scope to the adapter contract and tests; do not clone the broker or execution APIs.

- id: adopt-shared-development-terminal-in-tomorrow
  title: Replace Tomorrow's nonfunctional terminal clone with the shared session client
  material: no
  model: sonnet
  submitted-by: Codex operator-directed orchestrator remediation
  depends: [contracts-tomorrow-development-session-embed, beethoven:shared-development-terminal-sdk-and-madeus-client]
  proof: Tomorrow typecheck/unit/e2e suites pass and a real session state is rendered without fabricated demo data
  prompt: |
    Replace Tomorrow's copied DevelopmentTerminal and missing execution endpoint with the shared session client. Preserve styling, add authenticated project-scoped intake and streamed reconnectable events, and render the common plan/steering/diff/test/integration/release/journey proof surface. Add regression tests for offline, unknown, blocked, merged-only, and deployed-and-verified states.

PROJECT: pareto-2080

- id: contracts-pareto-development-session-embed
  title: Pin Pareto project and financial-risk steering boundaries for the shared terminal
  material: yes
  model: sonnet
  submitted-by: Codex operator-directed orchestrator remediation
  depends: [beethoven:shared-development-terminal-sdk-and-madeus-client, beethoven:foulkon-illuminati-apparently-steering-hooks]
  proof: the Pareto adapter contract test passes and financial/legal context cannot broaden execution permissions
  prompt: |
    Define Pareto's shared terminal adapter contract with project identity, scoped auth, financial/legal steering context, proof presentation, and explicit separation between advice/governance and repository execution authority. Limit implementation to contract and tests.

- id: adopt-shared-development-terminal-in-pareto
  title: Replace Pareto's terminal clone with the shared session client
  material: yes
  model: sonnet
  submitted-by: Codex operator-directed orchestrator remediation
  depends: [contracts-pareto-development-session-embed, beethoven:shared-development-terminal-sdk-and-madeus-client]
  proof: Pareto typecheck/unit/e2e suites pass and custody-sensitive actions produce visible steering holds before execution
  prompt: |
    Replace Pareto's copied/nonfunctional terminal with the shared session client. Preserve product styling, add reconnectable event streaming and exact proof links, and display Foulkon/Illuminati/Apparently decisions for custody-sensitive work without granting those advisers shell authority. Remove fabricated success states and add auth, steering-hold, merged-only, and production-journey tests.

PROJECT: illuminati

- id: contracts-illuminati-development-session-embed
  title: Pin Illuminati steering-adapter and session-display boundaries
  material: yes
  model: opus
  submitted-by: Codex operator-directed orchestrator remediation
  depends: [beethoven:shared-development-terminal-sdk-and-madeus-client, beethoven:foulkon-illuminati-apparently-steering-hooks]
  proof: the Illuminati adapter contract tests pass and risk guidance is a signed receipt rather than executable authority
  prompt: |
    Define Illuminati's two bounded roles: a signed risk-steering adapter into the shared broker and a thin project-scoped terminal client. Specify auth, decision schema/version, latency, fallback, override audit, proof display, and strict separation from shell/release authority. Limit scope to contracts and tests.

- id: adopt-shared-development-terminal-in-illuminati
  title: Replace missing WebSocket and demo fallback with the shared session client
  material: yes
  model: sonnet
  submitted-by: Codex operator-directed orchestrator remediation
  depends: [contracts-illuminati-development-session-embed, beethoven:shared-development-terminal-sdk-and-madeus-client]
  proof: Illuminati typecheck/unit/e2e suites pass; disconnect never loads demo agents or deployments in production
  prompt: |
    Remove the nonexistent /api/terminal/ws loop, demo-state production fallback, and fake cascade responses. Adopt the shared authenticated session client with cursor replay and explicit UNKNOWN/OFFLINE states. Render real steering decisions and proof receipts. Add tests for connection failure, resume, duplicate event suppression, signed decision display, and absence of demo data outside fixtures.

PROJECT: apparently-law

- id: contracts-apparently-law-development-session-embed
  title: Pin Tomorrow Law/Apparently Law legal-context boundaries for the shared terminal
  material: yes
  model: opus
  submitted-by: Codex operator-directed orchestrator remediation
  depends: [beethoven:shared-development-terminal-sdk-and-madeus-client, beethoven:foulkon-illuminati-apparently-steering-hooks]
  proof: the Apparently Law adapter contract tests pass and privileged/legal context is redacted and scope-limited
  prompt: |
    Define the Apparently Law/Tomorrow Law shared terminal adapter with project identity, scoped authentication, privileged-data redaction, legal steering contribution, evidence links, and override policy. Legal analysis may advise or hold governed actions but may not inherit repository execution credentials. Limit scope to contracts and tests.

- id: adopt-shared-development-terminal-in-apparently-law
  title: Add the proof-backed shared development terminal to Apparently Law/Tomorrow Law
  material: yes
  model: sonnet
  submitted-by: Codex operator-directed orchestrator remediation
  depends: [contracts-apparently-law-development-session-embed, beethoven:shared-development-terminal-sdk-and-madeus-client]
  proof: Apparently Law typecheck/unit/e2e suites pass with privileged-data redaction, reconnect, steering, and production-proof cases
  prompt: |
    Integrate the shared terminal client as a project-scoped development surface. Show real plan, streamed work, steering, diff/test/integration/release/journey evidence while redacting privileged or secret content. Add reconnect, access-control, redaction, hold/override, merged-only, and deployed-and-verified tests. Do not create a product-local coding engine.
