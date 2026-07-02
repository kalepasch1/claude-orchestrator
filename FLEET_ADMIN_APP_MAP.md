# Fleet Admin — App Onboarding Map

How each app joins the Fleet Admin Control Plane. Onboarding is deliberately tiny and
identical for every app — that is the "accept new projects easily" guarantee:

1. **Emit** — map the app's existing admin surface to canonical `AdminEvent`s and POST
   them to the plane (`POST {ORCHESTRATOR}/api/fleet/ingest`). One adapter module.
2. **Execute** — add `POST /api/fleet/execute` that runs a cleared `AdminAction` with the
   app's OWN credentials/RLS and returns `{ok, ref, undoToken?}`. One endpoint.
3. **Env** — set `FLEET_SHARED_SECRET` (same value everywhere) + `ORCHESTRATOR_INGEST_URL`,
   and register the app's base URL on the plane as `FLEET_URL_<PRODUCT>`.

The plane never touches an app's database directly. It governs (constitution + autonomy
dial), auto-runs the safe 95% by delegating to `/api/fleet/execute`, and mirrors the rest
into Bear's Smarter inbox. Every action leaves a signed receipt.

Reference implementation: **Apparently** (`server/utils/fleet-adapter.ts` +
`server/api/fleet/execute.post.ts`). Every other app copies this shape.

| App | Stack | Existing admin surface | Primary domains | Onboarding |
|-----|-------|------------------------|-----------------|------------|
| **apparently** | Nuxt 4 + Supabase | `admin-board.ts` (severity ladder + categories), 200+ engines, audit-chain | trust_safety (compliance), infra, users_access | ✅ **Reference adapter built** — wire `ORCHESTRATOR_INGEST_URL`, then feed `admin-board` posts through `toAdminEvent()` |
| **tomorrow** | Nuxt + Supabase | `adminAudit`, `adminAuth`, admin CRM, `middleware/admin` | users_access, trust_safety (CFTC), billing, infra | Copy adapter; map CRM/audit rows → events; execute for account/billing verbs |
| **smarter** | Nuxt 3 + Supabase | `adminTasks.ts`, Now/Approve, governance trust dial | users_access, billing | ✅ **Is the approval surface** (`/fleet`). Also emits its own admin via the same adapter shape |
| **galop** | Cloudflare + Next console + Supabase edge | `console/lib/admin.ts`, `console/app/api/admin`, `racefeed/.../_shared/admin.ts` | billing (payouts/chargebacks), users_access (KYC/geo), trust_safety (fraud), infra | Adapter in `console`; execute for refund/payout-hold/geo-block. **Billing gated hardest** |
| **pareto (2080)** | Nuxt + Square | `middleware/auth.global`, investment/rewards composables | billing (Square money movement), users_access, infra | Adapter; **all money verbs always-human** (never auto-move funds) |
| **tomorrow** | — | see above | — | — |
| **Sustainable_Barks** | Nuxt + Supabase | `pages/admin` (orders, hotel partners, welcome cards) | billing (bundle orders), users_access (hotel partners), infra | Adapter; execute for refund/order-fix/partner-provision |
| **darwn (darwinlife)** | Nuxt + Prisma | `middleware/admin-auth`, `server/api/admin`, `layouts/admin` | users_access, trust_safety, billing | Adapter; execute against Prisma with existing admin-auth |
| **hisanta** | Expo/RN + Supabase | `app/admin` | infra, users_access, billing | Adapter in the Supabase edge/server layer; execute for account/billing verbs |
| **beethoven / orchestrator** | Nuxt + Supabase + Py runner | IS the control plane | infra (self-monitoring) | Hosts the plane; may emit infra events about its own runner health |
| **_any new app_** | any | — | — | Implement the 3 steps above (`FleetAdminAdapter` contract) — no schema negotiation |

## Domain autonomy ceilings (applied uniformly across every app)

- **users_access** — auto: reversible password resets, in-policy role grants. Always-human: suspend, ban, delete, KYC rejection, admin-role grant.
- **billing** — auto: reversible refunds ≤ $50, payment retries, dunning. Always-human: chargeback disputes, exception credits, price changes, any fund movement above the cap.
- **trust_safety** — auto: spam removal, rate-limits. Always-human: account termination, appeals, reports to authorities.
- **infra** — ceiling is **co_pilot** (never silently acts on prod). Auto-eligible verbs still propose-for-approval by default. Always-human: production-data mutation, schema migrations, secret rotation, security-incident response.

These live in `@darwin/kernel/fleetAdmin` (`DEFAULT_DOMAIN_POLICIES`) and can only be
loosened by a human-confirmed promotion from the escalation-learning flywheel.
