PROJECT: smarter

# Batch 3 — the CLIENT-FACING gateway + the associate CAREER VAULT. Both EXTEND existing substrate, do NOT
# rebuild: the hosted portal already exists (server/utils/counterpartyPortal.ts = HMAC magic-link, zero-login;
# pages/portal.vue; server/api/portal/*), and the career base exists (server/utils/secondBrain.ts + resume.ts +
# worth.ts + lateral.ts + jobCrawler.ts). Email parity is now real (Gmail polling active per git log) — reuse
# server/utils/emailSync.ts. Redaction is NER-assisted (redact() in server/utils/distillation.ts). Same hard
# rules: mock-degradable, qc.ts + Policy Constitution + <TrustBadge> on generated legal text, respect the trust
# dial, persist via kv.ts, brand gating (unbranded-premium at launch, white-label when the firm pays), never
# break the seed, `npx vue-tsc --noEmit` clean per commit.

- id: client-portal-engine
  title: Client trust portal engine (magic-link, zero-login, email-parity)
  material: yes
  model: opus
  depends: []
  proof: `npx vue-tsc --noEmit` exits 0
  prompt: |
    Extend the hosted-portal pattern in server/utils/counterpartyPortal.ts into a CLIENT trust portal engine
    (server/utils/clientPortal.ts + server/api/client-portal/*). Per client + matter, HMAC magic-link (no account)
    exposes the client-facing state: (a) documents/info WE NEED FROM THEM as typed upload slots with a
    completeness check, (b) every deliverable/request with live status + which side it's waiting on + an ETA,
    (c) the client's outstanding tasks. Reuse the token/TTL/HMAC approach already in counterpartyPortal.ts and
    read matter state from state.ts / cockpit.ts / closingTracker.ts / obligations.ts. Material: it gates access
    to client-confidential matter state via tokens. Keep it mock-degradable and brand-aware (brand.ts).

- id: client-portal-page
  title: The client "Now" landing page (3-section simplicity + uploads + approvals)
  material: no
  model: sonnet
  depends: [client-portal-engine]
  proof: `npx vue-tsc --noEmit` exits 0
  prompt: |
    Build pages/client/[token].vue — a Smarter-simple client landing mirroring Now: three sections — "What we
    need from you (N)", "Where your matter stands", "Waiting on your approval". Typed document upload into the
    slots from client-portal-engine (validate completeness, auto-chase missing). One-tap client approvals
    (confirm a term, approve a draft, e-sign) with bundled side-effects. Premium look, unbranded at launch,
    white-label when the firm's institutional plan is active (brand.ts). Mobile-first. No sidebar (hosted route,
    like pages/portal.vue / pages/room/[token].vue / pages/intake/[token].vue).

- id: client-deliverable-transparency
  title: Live deliverable status + responsible-side + SLA clock (the firm-speed forcing function)
  material: no
  model: sonnet
  depends: [client-portal-engine]
  proof: `npx vue-tsc --noEmit` exits 0
  prompt: |
    In the client portal, render each request/deliverable with a live status, WHICH SIDE it's waiting on
    (client / us / opposing / court), an ETA, and an SLA clock. When the firm is the bottleneck it is visible to
    the client — the structural pressure that forces the firm to move faster. Compute from cockpit.ts /
    closingTracker.ts / obligations.ts / docketSentinel.ts. Read-only to the client; do not expose internal notes
    or privileged content (respect dataPosture).

- id: client-email-parity
  title: Full email parity — nothing is forced into the portal
  material: no
  model: sonnet
  depends: [client-portal-engine]
  proof: `npx vue-tsc --noEmit` exits 0
  prompt: |
    Make the portal a BETTER alternative, never a requirement. A client who never logs in still receives every
    request, follow-up, and status update by email, and their email replies + attachments are ingested back into
    the SAME portal state (uploads land in the right slot, approvals via email reply are recorded). Reuse
    server/utils/emailSync.ts (Gmail polling is active) + the intake/ingest pipeline. The magic-link portal and
    the email thread stay in lockstep — one source of truth, two front doors.

- id: client-warroom-view
  title: Engagement-scoped client view of the negotiation room
  material: yes
  model: sonnet
  depends: [client-portal-engine]
  proof: `npx vue-tsc --noEmit` exits 0
  prompt: |
    Give the client an engagement-scoped view of the negotiation room (read-only OR participatory depending on a
    per-engagement setting): live clause positions, status, and history — radical transparency that builds trust
    and demos Smarter to the client's other firms. Reuse the hosted room (pages/room/[token].vue, hosted.ts) with
    a client-scoped token. Material: exposes negotiation state to the client — gate by engagement setting +
    access control; never leak our internal strategy/dealIntel to the client side.

- id: client-ask-my-matter
  title: Privilege-safe "ask about my matter" for the client
  material: yes
  model: sonnet
  depends: [client-portal-engine]
  proof: `npx vue-tsc --noEmit` exits 0
  prompt: |
    Add a client-facing "ask about my matter" Q&A scoped strictly to that client's own matter (reuse firmBrain.ts
    but hard-scope to the client's matter ids), routed through dataPosture.prepareForModel so nothing privileged
    or cross-client is ever exposed. Answers are cited to client-visible artifacts only. Material: client-facing
    generative answers over matter data — must be scope- and privilege-guarded + QC-gated.

- id: career-vault-curation
  title: Role-curated career vault (auto-select the best relevant work per lateral role)
  material: no
  model: sonnet
  depends: []
  proof: `npx vue-tsc --noEmit` exits 0
  prompt: |
    Extend the associate's second brain (server/utils/secondBrain.ts) + resume.ts + worth.ts into a role-curated
    career vault: given a target lateral role (from lateral.ts / jobCrawler.ts), auto-select the associate's
    single strongest, most-relevant work sample — ranked by relevance to the role + OUTCOME (the memo/redline that
    actually won or closed) + reliability evidence (reliabilityScore.ts). Owned by the associate, portable,
    auto-updating as experience grows. Endpoint returns the curated package for a given role id.

- id: career-vault-cleanroom
  title: Clean-room, verified, de-identified work samples + one-tap apply
  material: yes
  model: opus
  depends: [career-vault-curation]
  proof: `npx vue-tsc --noEmit` exits 0
  prompt: |
    Every work sample shared externally MUST pass through the redact()/distill() gate (server/utils/distillation.ts,
    now NER-assisted) so client identity + privileged content are stripped BEFORE it leaves — turning "I can't show
    my work product" into a permissible, de-identified writing sample. Attach a provenance badge (real work,
    QC-passed, signed via trustReceipts) so the hiring firm trusts it's genuine, not fabricated. Add one-tap "apply
    with my best work": assemble the role-tailored résumé + the best clean-room sample + a fitted cover note as one
    package. Material: external egress of derived work product — the redaction guarantee + assertNoClientData guard
    are mandatory.

OPERATOR:
  - Custom domains + white-label branding for client portals (institutional-plan firms); confirm PORTAL_SECRET is set in prod for HMAC token signing.
  - E-signature provider (DocuSign consent flow is live) for client one-tap approvals/e-sign.
  - LEGAL SIGN-OFF: confirm the clean-room redaction standard is sufficient for externally-shared work samples under the applicable bar confidentiality rules before the career-vault external-share ships; and confirm the client "ask about my matter" scope-guard passes a privilege review.
