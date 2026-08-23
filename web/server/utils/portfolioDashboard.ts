/**
 * portfolioDashboard.ts — the multi-entity portfolio dashboard, built ONCE and
 * consumed twice.
 *
 * TWO CONSUMERS, ONE MACHINE
 * --------------------------
 *   (i)  the private madeus.cc cockpit, where the operator sees personal +
 *        portfolio + company work in one queue, and
 *   (ii) the version embedded inside Apparently, which is the real customer
 *        surface: in-house teams running several products/subsidiaries.
 *
 * They differ by MODE, not by codebase. `mode` changes what is shown (the
 * private cockpit may surface operator-only affordances; the embedded one must
 * not), and nothing else. Two implementations would drift within a month, and
 * the embedded one is the one customers see.
 *
 * WHAT THE SCREEN HAS TO ANSWER
 * -----------------------------
 * "What do all my products/entities need from me right now." So the ordering
 * rule is URGENCY, not entity name and not recency: the cross-entity approvals
 * inbox is ranked by how much it costs to keep waiting, and per-entity cards
 * carry fleet activity, pending approvals, next waves + ETA, compliance posture
 * and latest shipped.
 *
 * Pure and dependency-free: all data arrives as fixtures/probes, so both modes
 * and N seeded entities are testable without a database.
 */

export type DashboardMode = 'private_cockpit' | 'apparently_embedded'

export interface EntityFacts {
  entityId: string
  displayName: string
  runningTasks: number
  queuedTasks: number
  pendingApprovals: ApprovalFacts[]
  nextWave?: { waveId: string; label: string; etaMs: number | null }
  compliance?: { state: 'connected' | 'not_connected' | 'disabled'; headline: string }
  latestShipped?: { label: string; at: number }
}

export interface ApprovalFacts {
  approvalId: string
  entityId: string
  summary: string
  /** ms epoch when it started waiting. */
  waitingSince: number
  /** Quantified exposure, when the gate carries one. */
  estimateUsd?: number
  /** A blocking gate stops a release; an advisory one does not. */
  blocking?: boolean
}

export interface EntityCard {
  entityId: string
  displayName: string
  fleet: { running: number; queued: number }
  pendingApprovalCount: number
  nextWave: { waveId: string; label: string; etaMs: number | null } | null
  compliance: { state: string; headline: string }
  latestShipped: { label: string; at: number } | null
  /** True when this card needs the human today. Drives visual emphasis. */
  needsYou: boolean
}

export interface RankedApproval extends ApprovalFacts {
  waitingHours: number
  urgency: number
  /** Why it ranked here, in words. A number nobody can explain gets ignored. */
  rationale: string
}

export interface DashboardView {
  mode: DashboardMode
  entities: EntityCard[]
  /** Cross-entity, most urgent first. THE answer to "what needs me now". */
  inbox: RankedApproval[]
  totals: { entities: number; running: number; queued: number; pendingApprovals: number }
  /** Present only in the private cockpit. Absent — not empty — when embedded. */
  operatorTools?: { manageTenants: string; fleetControl: string }
}

const HOUR_MS = 3_600_000

/**
 * Urgency = money x waiting x blocking.
 *
 * Deliberately simple and explainable. The alternative — a learned score — is
 * unauditable at exactly the moment someone asks "why is this at the top", and
 * an inbox nobody trusts gets scrolled past.
 *
 * Waiting time uses log growth so a two-week-old item outranks a two-hour-old
 * one without a month-old one drowning everything else forever.
 */
export function urgencyOf(a: ApprovalFacts, now: number): { urgency: number; waitingHours: number; rationale: string } {
  const waitingMs = Math.max(0, now - (Number(a.waitingSince) || now))
  const waitingHours = waitingMs / HOUR_MS
  const waitScore = Math.log10(1 + waitingHours)          // 0 at 0h, ~1.4 at 24h
  const money = Math.max(0, Number(a.estimateUsd) || 0)
  const moneyScore = money > 0 ? Math.log10(1 + money) : 0 // 0 at $0, 5 at $100k
  const blockingScore = a.blocking ? 2 : 0

  const urgency = Number((waitScore + moneyScore + blockingScore).toFixed(4))

  const bits: string[] = []
  if (a.blocking) bits.push('blocking a release')
  if (money > 0) bits.push(`$${Math.round(money).toLocaleString('en-US')} at stake`)
  bits.push(waitingHours < 1
    ? 'just arrived'
    : `waiting ${waitingHours < 24 ? `${Math.round(waitingHours)}h` : `${Math.round(waitingHours / 24)}d`}`)

  return { urgency, waitingHours: Number(waitingHours.toFixed(2)), rationale: bits.join('; ') }
}

function toCard(e: EntityFacts): EntityCard {
  const pending = Array.isArray(e.pendingApprovals) ? e.pendingApprovals : []
  return {
    entityId: e.entityId,
    displayName: e.displayName || e.entityId,
    fleet: { running: Math.max(0, e.runningTasks || 0), queued: Math.max(0, e.queuedTasks || 0) },
    pendingApprovalCount: pending.length,
    nextWave: e.nextWave ?? null,
    compliance: e.compliance ?? { state: 'not_connected', headline: 'Compliance not connected.' },
    latestShipped: e.latestShipped ?? null,
    // "Needs you" means a HUMAN is the blocker — not that the fleet is busy.
    needsYou: pending.length > 0,
  }
}

/**
 * Build the one-screen view. Never throws; missing data becomes an empty card
 * rather than a missing entity, because an entity that silently vanishes from
 * this screen is an entity nobody notices is stuck.
 */
export function buildDashboard(
  mode: DashboardMode,
  entities: readonly EntityFacts[] | undefined | null,
  now: number = Date.now(),
): DashboardView {
  const list = Array.isArray(entities) ? entities.filter(e => e && e.entityId) : []
  const cards = list.map(toCard)

  const inbox: RankedApproval[] = list
    .flatMap(e => (Array.isArray(e.pendingApprovals) ? e.pendingApprovals : [])
      .filter(a => a && a.approvalId)
      .map(a => ({ ...a, entityId: a.entityId || e.entityId })))
    .map(a => ({ ...a, ...urgencyOf(a, now) }))
    // Tie-break on approvalId so the order is STABLE across renders; an inbox
    // that reshuffles on refresh is one the eye cannot track.
    .sort((x, y) => y.urgency - x.urgency || x.approvalId.localeCompare(y.approvalId))

  const view: DashboardView = {
    mode,
    entities: cards,
    inbox,
    totals: {
      entities: cards.length,
      running: cards.reduce((s, c) => s + c.fleet.running, 0),
      queued: cards.reduce((s, c) => s + c.fleet.queued, 0),
      pendingApprovals: inbox.length,
    },
  }

  // Operator-only affordances exist ONLY in the private cockpit. Omitted rather
  // than emptied: a customer-facing bundle should not even carry the shape.
  if (mode === 'private_cockpit') {
    view.operatorTools = { manageTenants: '/admin/tenants', fleetControl: '/admin/fleet' }
  }
  return view
}

// ── Onboarding ──────────────────────────────────────────────────────────────

export const ONBOARDING_STEPS = [
  'connect_github',
  'connect_deploy_target',
  'register_projects',
  'declare_constitution',
  'first_outcome',
] as const
export type OnboardingStep = (typeof ONBOARDING_STEPS)[number]

export interface OnboardingState {
  githubInstalled?: boolean
  selectedRepos?: string[]
  deployTarget?: string
  supabaseRef?: string
  projects?: string[]
  constitutionTemplate?: string
  firstOutcomeSubmitted?: boolean
}

export interface OnboardingProgress {
  step: OnboardingStep | 'complete'
  completed: OnboardingStep[]
  blockedBy?: string
  /** NO public self-serve signup or billing for Madeus itself. Stated in the
   *  data so a future UI cannot quietly add one and call it a step. */
  selfServeBilling: false
}

/**
 * Where onboarding stands. Order is fixed and each step gates the next: you
 * cannot register projects before a repo exists to register.
 *
 * The optional Supabase connection is genuinely optional and never blocks.
 */
export function onboardingProgress(state: OnboardingState | undefined | null): OnboardingProgress {
  const s = state || {}
  const completed: OnboardingStep[] = []

  if (s.githubInstalled && (s.selectedRepos?.length ?? 0) > 0) completed.push('connect_github')
  else return { step: 'connect_github', completed, blockedBy: 'install the GitHub App and select at least one repo', selfServeBilling: false }

  if (s.deployTarget) completed.push('connect_deploy_target')
  else return { step: 'connect_deploy_target', completed, blockedBy: 'choose a deploy target (Supabase is optional)', selfServeBilling: false }

  if ((s.projects?.length ?? 0) > 0) completed.push('register_projects')
  else return { step: 'register_projects', completed, blockedBy: 'register at least one project/product', selfServeBilling: false }

  if (s.constitutionTemplate) completed.push('declare_constitution')
  else return { step: 'declare_constitution', completed, blockedBy: 'pick a darwin-kernel constitution template (fleet may/may-not, materiality, approval rules)', selfServeBilling: false }

  if (s.firstOutcomeSubmitted) {
    completed.push('first_outcome')
    return { step: 'complete', completed, selfServeBilling: false }
  }
  return { step: 'first_outcome', completed, blockedBy: 'send one outcome through the clarify flow', selfServeBilling: false }
}
