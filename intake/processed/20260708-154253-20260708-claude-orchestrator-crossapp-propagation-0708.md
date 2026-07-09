PROJECT: claude-orchestrator

# Standing cross-app learning + propagation layer (2026-07-08). Goal: any merged advancement in
# any fleet app (tomorrow, apparently, smarter, hisanta, galop, pareto-2080) is automatically
# evaluated for applicability to the others and, where applicable, queued as adapted tasks — so
# the fleet improves together. Builds on capability.py registry + candidate_shared.py. SPEC.md
# invariants apply: privacy.scrub() before any capability/knowledge write, provenance.record() on
# publish/instantiate, upsert-only writes, material changes surface as approval cards.

- id: fleet-pattern-library
  title: Canonical cross-repo pattern library injected into every generated prompt
  material: no
  model: sonnet
  depends: []
  proof: `python3 -m pytest runner/tests -q` exits 0
  prompt: |
    Create a curated, machine-readable pattern library (runner/patterns/ or packages/ — match repo
    layout) capturing the fleet-wide conventions that already exist implicitly: fail-closed auth
    gates (requireAuth-first / requireWorkspaceAccess / requireOwnership), default-deny allowlists,
    RLS-first access control, idempotent upserts + deterministic IDs, pure-function engines with
    injected clock, structured '[CODE] message' errors, token-contract styling, no hardcoded model
    IDs, PII scrubbing before persistence. Each pattern: id, statement, per-project applicability
    map (which repos + local idiom, e.g. smarter=requireWorkspaceAccess, pareto=requireOwnership),
    and a grep-able detection hint. Then wire planner.py (which already reads SPEC.md) to inject
    the applicable patterns into every generated sub-task prompt for that project. Unit tests:
    library validates against a schema; planner output for each project contains its applicable
    patterns; unknown project degrades gracefully.

- id: merge-propagation-loop
  title: On MERGED task, auto-evaluate cross-app applicability and draft adapted intake tasks
  material: yes
  model: opus
  depends: [fleet-pattern-library]
  proof: `python3 -m pytest runner/tests -q` exits 0
  prompt: |
    Implement the standing propagation loop: when a task reaches MERGED with tests_passed, classify
    what was built (use the capability registry embedding + the task prompt/diff summary) and score
    applicability to each OTHER fleet project (pgvector similarity against that project's
    capabilities + pattern-library applicability map). For matches above threshold, generate an
    adapted task block in the canonical intake format (PROJECT: <target> / id/title/material/model/
    depends/proof/prompt) with the prompt rewritten for the target repo's stack and conventions
    (pull from the pattern library + target CLAUDE.md), and drop it as a file into intake/ — never
    direct DB inserts, so intake validation + idempotency apply. Guardrails: material=yes on all
    propagated security/auth changes; per-source-task cap (max N propagations); dedupe via slug
    convention (prop-<sourceproject>-<sourceslug>); everything privacy.scrub()'d; an approval card
    summarizing each propagation batch. Run it from the existing periodic loop (match how other
    periodic modules register). Tests with synthetic merged outcomes: applicable → intake file
    emitted with valid format (reuse intake_watcher.parse in the test); below threshold → nothing;
    duplicate → skipped; scrub applied.

- id: convention-sync-fleetwide
  title: Sync scrubbed learned conventions into each repo's CLAUDE.md via normal tasks
  material: yes
  model: sonnet
  depends: [merge-propagation-loop]
  proof: `python3 -m pytest runner/tests -q` exits 0
  prompt: |
    The "Learned from merged work" CLAUDE.md sections are currently written per-repo and have been
    polluted (rate-limit banners) and inconsistent. Build the clean pipeline: learned conventions
    from outcomes flow through the banner/PII scrubber (from bandit-outcome-decontamination task),
    are deduped against the fleet pattern library (a convention already in the library is not
    re-appended per repo), and repo-specific learnings are applied by queueing a normal small task
    for that repo (intake drop) that edits its CLAUDE.md — giving diff review + approval — instead
    of any direct cross-repo file write from the orchestrator. Include a one-time cleanup batch:
    generate intake tasks for tomorrow and smarter that strip the existing "You've hit your weekly
    limit" banner sections from their CLAUDE.md files. Tests: pollution never reaches output;
    dedupe works; generated intake blocks parse.

- id: fleet-health-dashboard-panel
  title: Web dashboard panel — cross-app propagation + fleet convergence visibility
  material: no
  model: sonnet
  depends: [merge-propagation-loop]
  proof: `cd web && npm run build` exits 0
  prompt: |
    Add a "Fleet" panel to the web dashboard (web/ — Nuxt + Tailwind, match existing pages/
    components conventions): per-project queue depth and last-merge recency; propagation events
    (source task → targets, status of each propagated task); pattern-library adoption matrix
    (pattern × project: enforced / pending task / N/A, driven by the detection hints run by the
    runner and reported to a table); recent convention-sync activity. Read-only, polling (SPEC:
    no realtime streaming needed), RLS-safe queries via the existing client patterns. Keep it one
    page + small components; no new dependencies.

OPERATOR:
  - Review the first propagation batch manually before raising the applicability threshold/cap (tune after observing precision).
  - Approve the one-time CLAUDE.md cleanup tasks for tomorrow + smarter when they appear.
