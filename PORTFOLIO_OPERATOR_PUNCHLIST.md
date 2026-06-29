# Portfolio Operator Punch-List

Single actionable list of outstanding items across the seven properties, from a
full audit (2026-06-29). **Headline: there are no critical incomplete-wiring or
abandoned-phase blockers.** Each repo is functionally complete within its declared
scope. What remains is mostly **operator-gated** (env/keys/deploys) or
**counsel-gated** (legal sign-off) — i.e. things only you can do — plus a few
intentional phase-gated stubs.

Legend: **(A)** safe code-level gap · **(B)** operator-gated (env/keys/deploy) ·
**(C)** counsel/legal-gated · **(D)** prod-DB migration.

## Darwin Kernel (the new cross-product layer) — DONE
- Shared kernel built + tested (43/43 tests, 0 typecheck errors) at
  `claude-orchestrator/packages/darwin-kernel`.
- Adoption guide present in all six app repos (`DARWIN_KERNEL_ADOPTION.md`).
- **Operator step to activate (B):** vendor the kernel into each app (git subtree
  or private npm), set `DARWIN_SIGNING_PRIVATE_KEY_PEM` (reuse Tomorrow's
  `PROOF_SIGNING_PRIVATE_KEY_PEM` so the trust anchor is shared), and apply
  `packages/darwin-kernel/sql/0001_darwin_kernel.sql` once to the shared Supabase
  project. Then flip the per-repo wires in each adoption doc.

## Tomorrow
Mostly already-completed-in-later-sessions or operator/counsel-gated. **Do NOT
hand-edit** — it auto-merges to prod via the self-improvement loop.
- **(B)** Deploy `20260628000000_lending_vertical` migration (+ Prisma models +
  `prisma generate`) after a name-check + shadow dry-run.
- **(B)** Mirror S2S secrets to Vercel prod (`RISK_STUDIO_S2S_SECRET`,
  `RISK_STUDIO_ORACLE_SECRET`, bank/fabric S2S) and set `CRON_SECRET`,
  `EMAIL_PROVIDER`/`RESEND_API_KEY`.
- **(C)** Counsel-gated flags remain OFF by design: `RISK_STUDIO_INTERMEDIATION_ENABLED`,
  `RISK_STUDIO_BASIS_GAP_ENABLED`, `SETTLEMENT_SWEEP_ENABLED`, `CUSTODY_ENABLED`.
- Note: risk-studio bot registration + `assessRiskStudio` appear **already done**
  (Phase F) — the audit was reading an older marker. Verify before any action.

## Apparently
- **(C)** Reward-token rails + gaming-wrapper-arb feature flags need OCC carve-out
  + NFA/CFTC sign-off before enabling (`tenant_feature_flags`).
- **(B)** USPS/FedEx tracking calls in `promo-mail-prep.ts` need real API creds.
- **(A)** `@ts-nocheck` on ~5 API test files → convert to targeted `@ts-expect-error`
  (low value; do incrementally).
- **(A)** NV NGC-1 / NJ form field mappings — data-entry from regulator PDFs.

## Smarter
- **(B)** `@ht/ui` alias is hardcoded to an absolute path
  (`/Users/.../apparently/packages/ht-ui`) — a CI/other-machine blocker. Move to a
  workspace dep or publish the package before any shared deploy.
- **(A)** Intentional phase-gated stubs: OCR/redline extraction (`ingest/document.post.ts`),
  draft-send button (`WarRoomPanel.vue`). Complete when the upstream integrations land.
- **Strategic:** Smarter ≈ Tomorrow's War Room. Converge them on the kernel's
  capability registry (see adoption doc) rather than maintaining two engines.

## Pareto / 2080
- All 56 phases complete, 696 tests passing. No deploy blockers.
- **(A/B)** Trip-distance lookup is a great-circle stub with a safe default →
  optionally wire a geocoding service or a precomputed city-pair table.
- **(A/B)** Chrome-checkout ("Phase 6") escalates to manual L3 today → wire browser
  automation when ready.

## Galop
- **(B)** Weekly-digest email: set `DIGEST_SMTP_API_KEY` (currently logs only);
  finalize the digest view schema/date filter.
- **(A)** Small UX wiring: deep-link listener (`_layout.tsx`), video watch-fraction
  streak bonus (`useStreak.ts`), token-buy server sync (gated on `buy_tokens` RPC).
- **(B)** Expo v2 / expo-video migration (currently `@ts-expect-error` suppressed).

## Hisanta
- **Clean.** No code-level TODOs/stubs. Edge functions exist but aren't deployed
  (not required for the core app).
- **(B)** Deploy Supabase edge functions when you want server-side AI/letters live.

## Orchestrator
- **(B)** Web not yet deployed to Vercel (`DEPLOY.md`: push repo, `vercel --prod`,
  set `SUPABASE_URL`/`SUPABASE_KEY`).
- **(B)** Slack approvals: deploy `slack-notify` / `slack-interactions` edge
  functions, wire the INSERT-on-`approvals` DB webhook, set `SLACK_*` secrets.
- **(B)** Provider key rotation / batch features: set `ANTHROPIC_API_KEY`,
  `VERCEL_TOKEN`, Stripe live keys; point the launchd scheduler at the runner.

---

### What I deliberately did NOT do
- No edits to Tomorrow's prod-auto-merge source (risk of shipping a broken build via
  its self-improvement loop; its flagged items are already done or operator-gated).
- No prod-DB migrations, no entering of secrets/keys into Vercel/GitHub (prohibited
  + risky), no flipping counsel-gated legal flags.
- No "completing" of intentional phase-gated stubs that require real third-party
  integrations (OCR, geocoding, browser automation) — those are product decisions.
