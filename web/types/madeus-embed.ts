/**
 * madeus-embed.ts — the SHARED contracts for the multi-tenant Madeus layer,
 * its bidirectional embeds, and the cross-tenant hivemind.
 *
 * THIS FILE IS TYPES ONLY. No runtime code, no I/O, no Vue, no Nitro imports —
 * so both the madeus.cc console (web/) and every host app that embeds it can
 * depend on it without dragging a runtime along. Sibling tasks implement
 * AGAINST these; nothing here implements anything.
 *
 * The scope decision these types encode (round-11 supersession, strategy 4.12e
 * as revised) is worth stating in the contract itself, because it is the thing
 * a future task is most likely to get wrong:
 *
 *   madeus.cc stays PRIVATE. It is the operator's own cockpit and the shared
 *   portfolio engine. There is no public claude-preneur product, no public
 *   onboarding, and no separate tenant base to sell to. Tenancy exists here
 *   because APPARENTLY needs it — in-house teams running several
 *   products/subsidiaries at once are functionally multi-company — and the
 *   hivemind population is ALL APPARENTLY USERS, not Madeus customers.
 *
 * So `TenantId` below is an Apparently-side org, not a Madeus subscriber, and
 * `HivemindContribution` is anonymised at the source rather than trusted to be
 * anonymised by the reader.
 *
 * See MADEUS_CONTRACTS.md in this directory for the narrative version.
 */

// ── Identity ────────────────────────────────────────────────────────────────

/** An Apparently-side organisation. NOT a Madeus subscriber — see the header. */
export type TenantId = string

/** A user within a tenant. Stable across host apps. */
export type PrincipalId = string

/** The apps that can host an embed. madeus.cc is the private direct console. */
export type HostApp = 'apparently' | 'tomorrow' | 'pareto' | 'madeus'

/** Departments a fleet can be initiated for. Extend deliberately, not ad hoc. */
export type Department =
  | 'engineering'
  | 'legal'
  | 'finance'
  | 'marketing'
  | 'operations'
  | 'research'

// ── Tenancy and isolation ───────────────────────────────────────────────────

/**
 * The isolation guarantee a surface runs under.
 *
 * `strict` is the default and the only safe assumption: a query with no
 * explicit tenant scope must return NOTHING rather than everything. Implementors
 * are expected to enforce this at the row level (RLS), not in application code —
 * an app-side filter is a bug waiting for the one code path that forgets it.
 */
export type IsolationMode = 'strict' | 'shared_readonly'

export interface TenantContext {
  tenantId: TenantId
  principalId: PrincipalId
  hostApp: HostApp
  isolation: IsolationMode
  /** Departments this principal may initiate or steer fleets for. */
  departments: readonly Department[]
  /** ms epoch when this context was minted; embeds must treat it as expiring. */
  issuedAt: number
  expiresAt: number
}

/** A tenant that owns several entities (subsidiaries, products, brands). */
export interface EntityScope {
  entityId: string
  tenantId: TenantId
  displayName: string
  /** Entities may read siblings only when the tenant opts in explicitly. */
  siblingReadable: boolean
}

// ── Bidirectional embeds ────────────────────────────────────────────────────

/**
 * Which Madeus capability a host is mounting.
 *
 * Round 11 raised the bar from "the strip" to FULL capability parity, so this
 * union is the parity checklist: a host that mounts only `strip` is incomplete
 * by contract, not merely minimal.
 */
export type EmbedSurface =
  | 'strip'
  | 'universal_command'
  | 'fleet_dashboard'
  | 'waves_dashboard'
  | 'signoffs'
  | 'steering'
  | 'tenancy_admin'
  | 'intercompany'
  | 'department_fleet_init'

export interface EmbedMount {
  surface: EmbedSurface
  hostApp: HostApp
  context: TenantContext
  /** Entity the mount is scoped to, when the host is entity-aware. */
  entityId?: string
  /** Host-supplied element id the embed attaches to. */
  containerId: string
}

/**
 * Messages crossing the embed boundary. Bidirectional by design: the host can
 * drive the embed (`host_to_embed`) and the embed can ask the host to navigate
 * or to re-auth (`embed_to_host`).
 *
 * Every message carries its `context` so a receiver never has to infer the
 * tenant from ambient state — the class of bug that leaks one org's fleet into
 * another org's dashboard.
 */
export type EmbedDirection = 'host_to_embed' | 'embed_to_host'

export interface EmbedMessage<TPayload = unknown> {
  direction: EmbedDirection
  /** Dotted verb, e.g. 'fleet.initiate' or 'host.navigate'. */
  kind: string
  context: TenantContext
  payload: TPayload
  /** Correlates a response to its request; absent on fire-and-forget. */
  correlationId?: string
  sentAt: number
}

export interface EmbedAck {
  correlationId: string
  ok: boolean
  /** Present when ok is false. Human-readable, safe to surface. */
  error?: string
}

// ── Cross-tenant hivemind ───────────────────────────────────────────────────

/**
 * A learning contributed to the shared brain.
 *
 * Anonymised AT THE SOURCE: there is no tenantId or principalId on this type,
 * and that omission is the contract. A contribution that could be traced back
 * to the org that produced it is not a hivemind entry, it is a leak, and no
 * amount of downstream care fixes a payload that arrived identifying.
 */
export interface HivemindContribution {
  /** Opaque, non-reversible grouping key (e.g. HMAC of tenant+salt). */
  cohortKey: string
  department: Department
  /** What was attempted, in generic terms. No customer nouns. */
  situation: string
  /** What worked. No customer nouns. */
  resolution: string
  /** 0..1 — observed success rate for this resolution in this cohort. */
  outcomeScore: number
  observationCount: number
  contributedAt: number
}

export interface HivemindQuery {
  department: Department
  situation: string
  /** Caller's own cohort, so the engine can weight near-neighbours. */
  cohortKey: string
  limit?: number
}

export interface HivemindMatch {
  contribution: HivemindContribution
  /** 0..1 similarity of `situation` to the query. */
  relevance: number
  /** relevance x outcomeScore, the ranking metric. */
  rank: number
}

// ── Fleet initiation (department-scoped) ────────────────────────────────────

export interface FleetInitiationRequest {
  context: TenantContext
  department: Department
  entityId?: string
  /** Free-text operator intent; the planner decomposes it. */
  intent: string
  /** Hard ceiling the caller accepts. Absent means the tenant default. */
  maxParallelTasks?: number
}

export type FleetInitiationOutcome =
  | { ok: true; waveId: string; queuedTaskCount: number }
  | { ok: false; reason: string }

// ── Sign-offs and steering ──────────────────────────────────────────────────

export type SignoffState = 'pending' | 'approved' | 'rejected' | 'expired'

export interface Signoff {
  signoffId: string
  tenantId: TenantId
  entityId?: string
  department: Department
  subject: string
  state: SignoffState
  requestedBy: PrincipalId
  decidedBy?: PrincipalId
  requestedAt: number
  decidedAt?: number
}

export interface SteeringDirective {
  tenantId: TenantId
  department: Department
  /** Dotted key, e.g. 'model.tier' or 'risk.appetite'. */
  key: string
  value: string
  setBy: PrincipalId
  setAt: number
}

// ── Guard helper contracts (implemented by siblings, declared here) ─────────

/**
 * The single predicate every tenant-scoped read must pass. Declared here so all
 * siblings enforce the SAME rule rather than each inventing one; the
 * implementation belongs to the tenancy task.
 */
export type TenantGuard = (
  context: TenantContext,
  resourceTenantId: TenantId,
) => { allowed: boolean; reason?: string }

/** Anonymiser applied before anything reaches the hivemind. */
export type HivemindAnonymiser = (
  raw: { tenantId: TenantId; department: Department; situation: string; resolution: string },
  salt: string,
) => HivemindContribution
