/**
 * embedHandlers.ts — the request logic behind the three embed endpoints,
 * extracted from the Nitro handlers so it can be tested without a server.
 *
 * The handlers in server/api/embed/* are thin wrappers: read the request, call
 * one function here, translate the result to a status code. Everything that can
 * be got wrong — auth, tenant scoping, attribution — lives here where a test
 * can reach it.
 *
 * Every function takes its side effects as injected callbacks (`deps`). That is
 * not ceremony: it is what makes "a host from the wrong origin cannot submit"
 * an assertion rather than a hope.
 */
import {
  authorizeEmbed,
  validateApprovalDecision,
  validateOutcome,
  type EmbedKeyRecord,
} from './embedProtocol'

export interface EmbedRequest {
  key?: string
  origin?: string
  surface?: string
  body?: unknown
}

export interface EmbedResult {
  status: number
  body: Record<string, unknown>
}

const denied = (reason: string, status = 403): EmbedResult => ({ status, body: { ok: false, reason } })

// ── Submit an outcome from a host app ───────────────────────────────────────

export interface SubmitDeps {
  keys: readonly EmbedKeyRecord[]
  /** Persist the outcome; returns the queue id. */
  enqueue: (submission: {
    outcome: string; tenantId: string; hostApp: string
    entityId?: string; department?: string
  }) => Promise<string>
}

export async function handleSubmit(req: EmbedRequest, deps: SubmitDeps): Promise<EmbedResult> {
  const auth = authorizeEmbed(req.key, req.origin, req.surface ?? 'universal_command', deps.keys)
  if (!auth.ok) return denied(auth.reason || 'unauthorized')

  const parsed = validateOutcome(req.body, auth.tenantId as string)
  if (!parsed.ok) return { status: 400, body: { ok: false, reason: parsed.reason } }

  try {
    const queueId = await deps.enqueue(parsed.submission)
    return {
      status: 202,
      body: { ok: true, queueId, tenantId: auth.tenantId },
    }
  } catch (e) {
    // The host asked us to take work and we did not. Say so plainly rather than
    // returning 202 with nothing behind it — a silent drop here looks exactly
    // like success from the host page.
    return { status: 503, body: { ok: false, reason: `enqueue failed: ${(e as Error)?.message || 'unknown'}` } }
  }
}

// ── Read the fleet-status / approvals strip ─────────────────────────────────

export interface StatusDeps {
  keys: readonly EmbedKeyRecord[]
  /** MUST be tenant-scoped by the caller; the tenant id is passed explicitly. */
  fetchStatus: (tenantId: string) => Promise<{
    runningTasks: number
    queuedTasks: number
    pendingApprovals: Array<{ id: string; summary: string }>
  }>
}

export async function handleStatus(req: EmbedRequest, deps: StatusDeps): Promise<EmbedResult> {
  const auth = authorizeEmbed(req.key, req.origin, req.surface ?? 'strip', deps.keys)
  if (!auth.ok) return denied(auth.reason || 'unauthorized')
  try {
    const status = await deps.fetchStatus(auth.tenantId as string)
    return { status: 200, body: { ok: true, tenantId: auth.tenantId, ...status } }
  } catch (e) {
    return { status: 503, body: { ok: false, reason: `status unavailable: ${(e as Error)?.message || 'unknown'}` } }
  }
}

// ── Return leg: a decision made in a host app ───────────────────────────────

export interface DecisionDeps {
  keys: readonly EmbedKeyRecord[]
  /** The approval's owning tenant, or null if it does not exist. */
  approvalTenant: (approvalId: string) => Promise<string | null>
  /** Write decided_by / state back onto the approval. */
  applyDecision: (d: {
    approvalId: string; decision: 'approved' | 'rejected'; decidedBy: string
  }) => Promise<void>
  /** Attributed steering_events row. Failure here is reported, not swallowed. */
  recordSteering: (e: {
    approvalId: string; decidedBy: string; decidedByLabel?: string
    rationale?: string; hostApp: string; tenantId: string
  }) => Promise<boolean>
}

export async function handleDecision(req: EmbedRequest, deps: DecisionDeps): Promise<EmbedResult> {
  const auth = authorizeEmbed(req.key, req.origin, req.surface ?? 'signoffs', deps.keys)
  if (!auth.ok) return denied(auth.reason || 'unauthorized')

  const parsed = validateApprovalDecision(req.body)
  if (!parsed.ok) return { status: 400, body: { ok: false, reason: parsed.reason } }
  const d = parsed.decision

  // The approval must belong to the AUTHENTICATED tenant. Without this check a
  // valid key for tenant A could decide tenant B's cards by guessing an id —
  // the single most damaging bug this endpoint could have.
  const owner = await deps.approvalTenant(d.approvalId)
  if (owner === null) return { status: 404, body: { ok: false, reason: 'approval not found' } }
  if (owner !== auth.tenantId) {
    return denied('approval belongs to another tenant', 404)
  }

  await deps.applyDecision({ approvalId: d.approvalId, decision: d.decision, decidedBy: d.decidedBy })
  const steeringRecorded = await deps.recordSteering({
    approvalId: d.approvalId,
    decidedBy: d.decidedBy,
    decidedByLabel: d.decidedByLabel,
    rationale: d.rationale,
    hostApp: d.hostApp,
    tenantId: auth.tenantId as string,
  })

  // 200 with steeringRecorded:false is deliberate. The decision DID apply; the
  // audit row did not. Reporting that beats both pretending it worked and
  // rolling back a decision a human already made.
  return { status: 200, body: { ok: true, approvalId: d.approvalId, decision: d.decision, steeringRecorded } }
}
