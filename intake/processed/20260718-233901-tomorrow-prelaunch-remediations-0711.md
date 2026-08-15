PROJECT: tomorrow

# Pre-launch remediations for Tomorrow, embedded in its OS surfaces. Additive; posture-neutral; must not regress the
# posture-compliance suite. Conventions per tomorrow/CLAUDE.md (pure server/utils, requireVerifiedUser, tsc/vitest,
# lint:migrations). INSPECT FIRST; extend, don't duplicate.

- id: tomorrow-legible-proof-tile
  title: Plain-language proof/DecisionReceipt reveal on every 5/95 surface
  material: no
  model: sonnet
  depends: []
  proof: `npx tsc --noEmit --skipLibCheck` exits 0
  prompt: |
    Add a shared components/ui ProofReveal component that renders a DecisionReceipt / verifiableProof in plain language
    ("what we did, which policy/authority allowed it, the evidence") for non-expert users, with a raw/technical toggle.
    Wire it as the "proof" reveal of the DecisionBudget 5/95 tiles (allocation, approvals, war-room). Reuse design
    tokens; keep it accessible (semantic markup, focusable). Typecheck clean.

- id: tomorrow-accessibility-pass
  title: Accessibility pass on the primary surfaces (WCAG-AA-oriented)
  material: no
  model: sonnet
  depends: []
  proof: `npx tsc --noEmit --skipLibCheck` exits 0 AND `npm run lint:syntax` exits 0
  prompt: |
    Bring the primary surfaces (war-room, approvals, cockpit, allocation) toward WCAG AA: keyboard navigability +
    visible focus, ARIA roles/labels on interactive controls, color-contrast tokens, respects prefers-reduced-motion,
    screen-reader labels on charts (text summary alongside Chart.js canvases), and a large-type/high-contrast mode
    toggle in settings. Additive component/token changes only; no behavior change. Typecheck + lint:syntax clean.

- id: tomorrow-killswitch-reachability
  title: One-action global kill-switch reachable from every surface + reachability test
  material: yes
  model: opus
  depends: []
  proof: `npx vitest run --config vitest.pure.config.ts server/utils/safety/killSwitch.pure.test.ts` exits 0 AND `npx tsc --noEmit --skipLibCheck` exits 0
  prompt: |
    Ensure a single global kill-switch halts ALL autonomous/outbound activity fleet-of-features-wide and is reachable
    from every surface header. Add/confirm server/utils/safety/killSwitch.ts (pure state predicate consumed by the
    autonomy/approval paths) + killSwitch.pure.test.ts asserting: when engaged, every autonomous action-gate returns
    blocked (assert against the real gate functions), and it fails CLOSED (unknown state => blocked). Add the header
    control (components/ui) with a confirm. Do not change posture behavior; extend if a kill-switch already exists.

- id: tomorrow-ai-cost-ceiling
  title: Per-user / per-action AI + compute cost ceilings (fail-closed)
  material: yes
  model: sonnet
  depends: []
  proof: `npx vitest run --config vitest.pure.config.ts server/utils/cost/costCeiling.pure.test.ts` exits 0
  prompt: |
    Add server/utils/cost/costCeiling.ts — a PURE guard: given a user's/action's accumulated spend + a configured
    ceiling (env/KV), decide allow|hold(reason). Wire it as a precondition on the AI-call and autonomous-action paths so
    a runaway loop can't blow the budget; over-ceiling routes to a hold/approval, never a hard user-facing failure of
    unrelated features (fail-soft for reads, fail-closed for spend). Add costCeiling.pure.test.ts: under ceiling allows;
    over ceiling holds; missing config => conservative default hold on spend actions. Structured `[COST-CEILING]` errors.

- id: tomorrow-security-review-gate
  title: Security review of sensitive routes as an executable auth/RLS test (merge gate)
  material: yes
  model: opus
  depends: []
  proof: `npx vitest run server/utils/compliance/__tests__/authz.security.test.ts` exits 0
  prompt: |
    Add server/utils/compliance/authz.security.test.ts asserting, per the CLAUDE.md security rules, that EVERY sensitive
    server/api/* route calls requireAuth/requireVerifiedUser FIRST and that new-product/route access is default-deny
    (isProductAllowed / PRODUCT_ENABLED). Enumerate routes programmatically; a route missing the guard fails the test.
    Register it in the compliance.manifest.json suite list so the orchestrator compliance-gate runs it and BLOCKS a
    merge that ships an unguarded sensitive route. Do not change route behavior — lock it under test. (Run the
    security-review skill mindset: auth gates, default-deny, fail-closed, no secrets in code.)

OPERATOR:
  - Confirm the sensitive-route list + product allowlist is complete before the authz security test becomes a hard merge gate (counsel/security).
  - Accessibility: schedule a real assistive-tech pass (screen reader + keyboard-only) with a user before launch — automated checks are necessary, not sufficient.
