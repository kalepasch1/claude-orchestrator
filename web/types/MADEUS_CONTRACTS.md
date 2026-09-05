# Madeus shared contracts

Two files, and nothing else:

- `web/types/madeus-embed.ts` — TypeScript interfaces. Types only: no runtime
  code, no Vue, no Nitro, so both the private madeus.cc console and every host
  app can depend on them without dragging a runtime along.
- `web/supabase/migrations/002_madeus_tenancy_embed.sql` — table stubs and the
  isolation posture. No seed data, no views, no business logic.

Sibling tasks implement **against** these. This slice implements nothing.

## The scope decision the types encode

Round-11 supersession (strategy 4.12e as revised) changed what "multi-tenant"
means here, and getting it wrong is the most expensive mistake available:

**madeus.cc stays private.** It is the operator's own cockpit and the shared
portfolio engine. There is no public claude-preneur product, no public
onboarding or billing, and no separate Madeus tenant base to sell to.

Tenancy exists because **Apparently** needs it — in-house teams running several
products or subsidiaries at once are functionally multi-company — and the
hivemind population is **all Apparently users**, not Madeus customers.

So in these contracts:

- `TenantId` is an Apparently-side organisation, not a Madeus subscriber.
- `HostApp` is `apparently | tomorrow | pareto | madeus`, with Apparently the
  priority-1 mount.
- `EmbedSurface` is the full capability list, not the strip. Round 11 raised the
  bar to full parity, so a host that mounts only `strip` is incomplete *by
  contract* rather than merely minimal.

## Two invariants, enforced rather than documented

**Isolation is row-level.** Every tenant-scoped table has RLS enabled and ships
with *no* permissive policy. An unscoped query returns zero rows until a sibling
adds the policy its surface needs. Failing closed is the right default for a
table that spans organisations; an app-side filter is one forgotten code path
away from a cross-org leak. `TenantGuard` in the TS file declares the single
predicate every tenant-scoped read must pass, so siblings enforce the *same*
rule instead of each inventing one.

**The hivemind carries no identity.** `HivemindContribution` has no `tenantId`
and no `principalId`, and `madeus_hivemind_contributions` has no tenant column.
That omission *is* the contract: an entry traceable to the org that produced it
is a leak, not a learning, and no downstream care fixes a payload that arrived
identifying. Anonymisation happens at the source via `HivemindAnonymiser`, which
produces an opaque non-reversible `cohortKey` — enough to weight near-neighbours,
not enough to name anyone. The table's RLS therefore opens **reads** (safe,
because there is nothing to attribute) while leaving **writes** closed, so
contributions can only arrive through the anonymiser.

## Entities vs tenants

A tenant owns zero or more entities (subsidiaries, products, brands).
`EntityScope.siblingReadable` is opt-in: entities are isolated from each other
until the tenant explicitly says otherwise. Intercompany coordination is a
surface (`EmbedSurface.intercompany`), not a default permission.

## Messaging

`EmbedMessage` is bidirectional by design — the host drives the embed and the
embed asks the host to navigate or re-auth. Every message carries its
`TenantContext`, so a receiver never infers the tenant from ambient state. That
inference is exactly how one org's fleet ends up rendered in another org's
dashboard.

`TenantContext` carries `issuedAt`/`expiresAt`; embeds must treat it as expiring
rather than as a permanent grant.

## Extending this

`Department` and `EmbedSurface` are closed unions on purpose. Widen them in a
deliberate edit here — where every implementor sees the change — rather than by
passing a string through at a call site.
