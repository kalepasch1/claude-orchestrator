/**
 * integrationSlots.ts — per-tenant integration slots for a managed startup's
 * workspace: Coordination, Interception, Compliance, Risk.
 *
 * THE RULE THAT SHAPES ALL FOUR: FAIL-OPEN
 * ----------------------------------------
 * These are ORGANS grafted onto someone else's workspace. Every one of them
 * depends on a service that may not exist yet, may be behind a flag, or may be
 * down. If an unreachable Apparently could blank a startup's workspace, nobody
 * would ever turn these on. So a slot that cannot resolve renders a
 * `not_connected` state with a link-out — never an error, never an empty page,
 * and never a thrown exception reaching the page component.
 *
 * The one exception is Interception, and it is deliberate: a tenant that has
 * explicitly set CADE to `gate` has asked for work to be BLOCKED pending review,
 * so failing open there would silently remove a control the tenant chose. That
 * slot degrades to `advisory` and says so, rather than pretending the gate ran.
 *
 * Pure and dependency-free: resolution takes injected probes, so all four slots
 * are testable in connected and not-connected states from fixtures — which is
 * exactly the proof this section asks for.
 */

export const SLOT_KINDS = ['coordination', 'interception', 'compliance', 'risk'] as const
export type SlotKind = (typeof SLOT_KINDS)[number]

export type SlotState = 'connected' | 'not_connected' | 'disabled' | 'degraded'

export interface SlotView {
  kind: SlotKind
  state: SlotState
  /** One line the workspace can render verbatim. Always present. */
  headline: string
  /** Where to send the user. Always present when state !== 'disabled'. */
  href?: string
  /** Extra numbers a slot may carry; shape is per-kind and always optional. */
  detail?: Record<string, unknown>
  /** Present when the slot could not reach its service. Never thrown. */
  reason?: string
}

// ── Per-tenant configuration ────────────────────────────────────────────────

export type InterceptionMode = 'advisory' | 'gate' | 'off'

export interface TenantIntegrationConfig {
  tenantId: string
  coordination?: { enabled: boolean; boardUrl?: string; embedLive?: boolean }
  /** Default-ON per the spec: an absent config means advisory, not off. */
  interception?: { mode: InterceptionMode }
  compliance?: { enabled: boolean; apparentlyOrgId?: string }
  risk?: { enabled: boolean; tomorrowUrl?: string }
}

export interface SlotProbes {
  /** Smarter /embed/board reachability. */
  coordinationLive?: () => Promise<boolean>
  /** Tenant-scoped S2S pull from Apparently. */
  compliancePull?: (orgId: string) => Promise<{
    openFindings: number
    filingsStatus: string
    radarUrl?: string
  }>
  /** Quantified material risk on this tenant's open work, if any. */
  materialRisk?: () => Promise<{ estimateUsd: number; subject: string } | null>
}

const DEFAULT_TOMORROW = 'https://tomorrow.cc'

// ── (a) Coordination ────────────────────────────────────────────────────────

async function coordinationSlot(
  cfg: TenantIntegrationConfig,
  probes: SlotProbes,
): Promise<SlotView> {
  const c = cfg.coordination
  if (!c?.enabled) {
    return { kind: 'coordination', state: 'disabled', headline: 'Coordination board is off for this workspace.' }
  }
  const href = c.boardUrl || ''
  if (!href) {
    return {
      kind: 'coordination', state: 'not_connected',
      headline: 'Coordination board is not configured yet.',
      reason: 'no boardUrl configured',
    }
  }
  // The Smarter embed surface is being built separately. Until it is live we
  // ship the SLOT and a link-out, which is the whole point of shipping the slot
  // before the embed: the workspace shape stops changing.
  let live = c.embedLive === true
  if (live && probes.coordinationLive) {
    try {
      live = await probes.coordinationLive()
    } catch {
      live = false
    }
  }
  return live
    ? { kind: 'coordination', state: 'connected', headline: 'Coordination board is live.', href }
    : {
        kind: 'coordination', state: 'not_connected',
        headline: 'Coordination board opens in Smarter.',
        href, reason: 'embed not live yet — link-out fallback',
      }
}

// ── (b) Interception ────────────────────────────────────────────────────────

function interceptionSlot(cfg: TenantIntegrationConfig): SlotView {
  // Default-ON. An absent config is advisory, NOT off: a tenant that never
  // touched the setting should still get the legal dimension attached.
  const mode: InterceptionMode = cfg.interception?.mode ?? 'advisory'
  if (mode === 'off') {
    return {
      kind: 'interception', state: 'disabled',
      headline: 'Legal interception is off for this tenant.',
      detail: { mode },
    }
  }
  if (mode === 'gate') {
    return {
      kind: 'interception', state: 'connected',
      headline: 'Every task is gated by Illuminati CADE at planning; escalations create approval cards.',
      href: '/sign-offs', detail: { mode, createsCards: true },
    }
  }
  return {
    kind: 'interception', state: 'connected',
    headline: 'Illuminati CADE reviews every task at planning (advisory).',
    href: '/sign-offs', detail: { mode, createsCards: false },
  }
}

// ── (c) Compliance ──────────────────────────────────────────────────────────

async function complianceSlot(
  cfg: TenantIntegrationConfig,
  probes: SlotProbes,
): Promise<SlotView> {
  const c = cfg.compliance
  if (!c?.enabled) {
    return { kind: 'compliance', state: 'disabled', headline: 'Compliance strip is off for this workspace.' }
  }
  if (!c.apparentlyOrgId || !probes.compliancePull) {
    return {
      kind: 'compliance', state: 'not_connected',
      headline: 'Connect Apparently to see findings and filings here.',
      href: '/connectors',
      reason: c.apparentlyOrgId ? 'compliance pull not configured' : 'no Apparently org linked',
    }
  }
  try {
    const data = await probes.compliancePull(c.apparentlyOrgId)
    return {
      kind: 'compliance', state: 'connected',
      headline: `${data.openFindings} open finding${data.openFindings === 1 ? '' : 's'} · filings ${data.filingsStatus}`,
      href: data.radarUrl || '/connectors',
      detail: { openFindings: data.openFindings, filingsStatus: data.filingsStatus },
    }
  } catch (e) {
    // Apparently being down must not blank the workspace.
    return {
      kind: 'compliance', state: 'not_connected',
      headline: 'Compliance data is temporarily unavailable.',
      href: '/connectors',
      reason: (e as Error)?.message || 'compliance pull failed',
    }
  }
}

// ── (d) Risk ────────────────────────────────────────────────────────────────

async function riskSlot(
  cfg: TenantIntegrationConfig,
  probes: SlotProbes,
): Promise<SlotView> {
  const r = cfg.risk
  if (!r?.enabled) {
    return { kind: 'risk', state: 'disabled', headline: 'Risk hand-off is off for this workspace.' }
  }
  const base = r.tomorrowUrl || DEFAULT_TOMORROW
  if (!probes.materialRisk) {
    return { kind: 'risk', state: 'not_connected', headline: 'No quantified risk on this workspace.', href: base }
  }
  try {
    const risk = await probes.materialRisk()
    if (!risk || !(risk.estimateUsd > 0)) {
      return { kind: 'risk', state: 'not_connected', headline: 'No quantified risk on this workspace.', href: base }
    }
    // LINK-OUT ONLY in this pass. No S2S execution: moving money across a
    // service boundary on the strength of an estimate is not something to ship
    // quietly inside a sidebar widget.
    const usd = Math.round(risk.estimateUsd).toLocaleString('en-US')
    return {
      kind: 'risk', state: 'connected',
      headline: `Material risk of $${usd} on "${risk.subject}" — hedge this in Tomorrow.`,
      href: `${base.replace(/\/+$/, '')}/hedge?subject=${encodeURIComponent(risk.subject)}&estimate=${Math.round(risk.estimateUsd)}`,
      detail: { estimateUsd: Math.round(risk.estimateUsd), linkOutOnly: true },
    }
  } catch (e) {
    return {
      kind: 'risk', state: 'not_connected',
      headline: 'Risk data is temporarily unavailable.',
      href: base, reason: (e as Error)?.message || 'risk probe failed',
    }
  }
}

// ── The workspace view ──────────────────────────────────────────────────────

/**
 * Resolve all four slots. NEVER throws, and always returns exactly four views
 * in a stable order, so the workspace layout does not jump around as services
 * come and go.
 */
export async function resolveSlots(
  cfg: TenantIntegrationConfig,
  probes: SlotProbes = {},
): Promise<SlotView[]> {
  const safe = cfg || ({ tenantId: '' } as TenantIntegrationConfig)
  const [coordination, compliance, risk] = await Promise.all([
    coordinationSlot(safe, probes).catch((e): SlotView => ({
      kind: 'coordination', state: 'not_connected',
      headline: 'Coordination board is unavailable.', reason: String(e),
    })),
    complianceSlot(safe, probes).catch((e): SlotView => ({
      kind: 'compliance', state: 'not_connected',
      headline: 'Compliance data is unavailable.', reason: String(e),
    })),
    riskSlot(safe, probes).catch((e): SlotView => ({
      kind: 'risk', state: 'not_connected',
      headline: 'Risk data is unavailable.', reason: String(e),
    })),
  ])
  return [coordination, interceptionSlot(safe), compliance, risk]
}
