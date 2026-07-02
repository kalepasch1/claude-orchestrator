# emit() integration — exact call-sites

Each app posts events to the orchestrator RPC `emit_growth_event` (via `sdk/emit.ts` or `emit.py`).
Set these env vars in each app (values from the **claude-orchestrator** Supabase project settings):

```
ORCH_SUPABASE_URL=https://eatfwdzfurujcuwlhdgj.supabase.co
ORCH_SUPABASE_ANON_KEY=<orchestrator anon key>
GROWTH_ACTOR_SALT=<random secret, rotate periodically>   # same value across apps so a person maps 1:1
```

Rules: keep `event_type` + `segment` names **stable** (they're the optimization key). Pass raw ids as
`actorId` — the SDK hashes them locally; never send emails/names. Every monetary event needs `value`
+ a `dedupKey` (idempotent).

---

## Apparently (direct integration — Nuxt 4 / Nitro)

Copy `sdk/emit.ts` to `server/utils/growth.ts` (or import from a shared package).

**1. `visit` — client, once per landing session.** Add a Nuxt plugin `app/plugins/growth.client.ts`:
```ts
import { growth } from '~/server/utils/growth'
export default defineNuxtPlugin(() => {
  const seg = deriveSegmentFromRoute()        // e.g. 'apparently/licensing/dfs-startup'
  growth('apparently').track('visit', { channel: utmSource(), segment: seg })
})
```

**2. `signup` — org/account creation handler** (`server/api/**/register.post.ts` or the Supabase auth
hook). After the row is created:
```ts
await growth('apparently').track('signup', { actorId: user.id, segment, channel })
```

**3. `activate` — first real product action** (start a license application, run the legal-opinion
calculator). In that handler:
```ts
await growth('apparently').track('activate', { actorId: user.id, segment: 'apparently/licensing/<vertical>' })
```

**4. `qualified_lead` — ICP-fit intent** (legal-opinion quote requested, demo booked, multi-state
inquiry). In the intake handler:
```ts
await growth('apparently').track('qualified_lead', { actorId: leadId, segment, props: { states, urgency } })
```

**5. `revenue` — Stripe webhook** (`server/api/stripe/webhook.post.ts`, on
`checkout.session.completed` / `invoice.paid`):
```ts
await growth('apparently').track('revenue', {
  actorId: session.client_reference_id,
  value: session.amount_total / 100,
  segment, channel: 'paid',
  dedupKey: event.id,                 // Stripe event id — idempotent
})
```

**6. `content_published`** — in the content-engine publish step (or CMS hook):
```ts
await growth('apparently').track('content_published', { segment, props: { url, primary_keyword } })
```

**7. `churn` / `refund`** — subscription-cancel / Stripe `charge.refunded` handlers, symmetric to (5).

> Wrap each call in nothing — the SDK is already fail-soft. Do **not** await in a hot path if latency
> matters; drop the `await`.

---

## Tomorrow (via its self-improvement loop — do NOT hand-edit)

Per `PORTFOLIO_OPERATOR_PUNCHLIST.md`, Tomorrow auto-merges to prod through its own loop, so don't
patch its source directly. Instead file this as a `gtm` task in the orchestrator (the runner will
implement + PR it through Tomorrow's normal gates):

```
slug: instrument-growth-os-emit
kind: gtm
prompt: |
  Add Growth OS telemetry to Tomorrow using the emit SDK (sdk/emit.ts pattern). Env:
  ORCH_SUPABASE_URL, ORCH_SUPABASE_ANON_KEY, GROWTH_ACTOR_SALT. Emit, with stable event/segment names:
    - visit         : marketing/landing pages (client plugin), segment from route
    - qualified_lead: on IOI creation / negotiation-room open / Risk Studio discovery completion
    - signup        : ECP account creation
    - activate      : first negotiation or first Risk Studio structure generated
    - revenue       : on deal execution — value = fee on notional, dedupKey = trade/settlement id
    - expansion     : subsequent deals from an existing counterparty
  Hash actor ids locally (never send PII). Fail-soft. Segments like
  'tomorrow/hedging/community-bank', 'tomorrow/insurance-replacement/hnw',
  'tomorrow/risk-studio/corporate-treasury'. Acceptance: events land in the orchestrator
  growth_events; compute_growth_momentum() ranks Tomorrow on real data.
```

You can file it with the existing endpoint:
`POST /api/go-to-market { slug:"instrument-growth-os-emit", target_project:"tomorrow", product_name:"Tomorrow" }`
or insert a `tasks` row (kind='gtm').

---

## Same pattern, other apps (when promoted)
Apparently + Tomorrow first. Smarter, Pareto, Galop, Darwn reuse the identical SDK; only the segment
vocabulary and the `revenue`/`activate` trigger points differ. Galop's north-star is `activate`
(first pick) and its money event is `revenue` on handle; Pareto/Smarter are `signup`-led.
