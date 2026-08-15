# Apparently — 1-Click Filing Activation from Risk-Gradient Options (build now)

Operator directive 2026-07-30. When a Foulkon risk-gradient steering option implies a concrete
regulatory ACTION (filing, application, registration, report), the option already carries an
`activation` block (kind, what, indicative cost band, indicative timeline — shipped in the rapid
tribunal schema). Build the flow that turns that block into an executed filing with ONE explicit
human click.

## Flow
1. Gradient option selected → activation panel renders: what gets filed, where, full cost breakdown
   (agency fees + our fee), realistic timeline, the analysis behind it (linked verdict card /
   deep-pass memo), and what changes in the company's compliance posture when filed.
2. ONE CLICK = the human gate. The click is an informed approval: the panel must show the exact
   document(s) to be submitted (rendered, reviewable) BEFORE the button is active. No blind
   approvals — button disabled until the artifact preview has been opened.
3. On approval: autonomous preparation + submission via the existing filing infrastructure
   (Apparently's multi_jurisdiction_filings / license_renewal_events / form_field_mappings tables
   and filing pipelines — reuse, don't fork). Status tracking to completion with the same
   freshness-badge pattern; regulator correspondence auto-ingested back into the company context.
4. CURRENT + FUTURE STATE (operator): the panel shows the company's compliance posture BEFORE and
   AFTER the filing — "you are here → this filing moves you here" — sourced from the same live
   posture model the regulator portal renders. Filing decisions become posture-delta decisions.
5. Post-filing: the activation outcome (accepted/deficiency/timeline actual) feeds back into
   (a) the verdict corpus (real outcome data), (b) regulator_simulation's Beta-count observations
   (real flag/no-flag evidence), and (c) the License Timeline Board content (Part 9.4 #11).

## Guardrails (non-negotiable)
- Attorney-review flag for filings that constitute legal practice (per-jurisdiction table); those
  route through Brian's queue (§5.8b) with the same 1-click UX for HIM.
- Every submission carries the audit chain: gradient option → analysis → preview shown → who
  clicked → what was submitted → digest of the exact artifact.
- Cost/timeline shown are bands until confirmed; never invented precision.
- Kill-switch per company and global; a failed submission auto-opens a remediation task, never
  silently retries into a duplicate filing.

## 50-500X hooks
- "Filing-ready" badge ON the gradient option itself (before selection) — steering options that
  can be executed instantly are visibly more valuable than advice.
- Bundling: when one strategic choice implies filings in N jurisdictions, one approval executes
  the coordinated set with per-jurisdiction sequencing (the change-of-control scenario).
- The measured stat for marketing: "decision to filed: 11 minutes" vs. industry weeks.
