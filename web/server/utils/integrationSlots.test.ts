import { describe, expect, it } from 'vitest'
import { SLOT_KINDS, resolveSlots, type TenantIntegrationConfig } from './integrationSlots'

/**
 * The proof line: the workspace view renders all four slots in CONNECTED and
 * NOT-CONNECTED states from fixtures. Both halves are here.
 *
 * The tests that matter most are the fail-open ones. These organs are grafted
 * onto someone else's workspace, so an unreachable Apparently must degrade a
 * strip, not blank a page — if it could, nobody would enable them.
 */

const tenant = (over: Partial<TenantIntegrationConfig> = {}): TenantIntegrationConfig => ({
  tenantId: 'tenant-a',
  coordination: { enabled: true, boardUrl: 'https://smarter.example/embed/board', embedLive: true },
  interception: { mode: 'advisory' },
  compliance: { enabled: true, apparentlyOrgId: 'org-1' },
  risk: { enabled: true, tomorrowUrl: 'https://tomorrow.example' },
  ...over,
})

const connectedProbes = {
  coordinationLive: async () => true,
  compliancePull: async () => ({ openFindings: 3, filingsStatus: 'current', radarUrl: 'https://apparently.cc/radar' }),
  materialRisk: async () => ({ estimateUsd: 250_000, subject: 'FCA licensing exposure' }),
}

describe('the workspace always renders four slots', () => {
  it('returns exactly four, in a stable order, connected', async () => {
    const slots = await resolveSlots(tenant(), connectedProbes)
    expect(slots.map(s => s.kind)).toEqual([...SLOT_KINDS])
  })

  it('returns exactly four, in the same order, with nothing connected', async () => {
    const slots = await resolveSlots({ tenantId: 'tenant-b' }, {})
    expect(slots.map(s => s.kind)).toEqual([...SLOT_KINDS])
  })

  it('every slot always carries a renderable headline', async () => {
    for (const probes of [connectedProbes, {}]) {
      const slots = await resolveSlots(tenant(), probes)
      for (const s of slots) {
        expect(typeof s.headline).toBe('string')
        expect(s.headline.length).toBeGreaterThan(0)
      }
    }
  })

  it('every non-disabled slot offers somewhere to go', async () => {
    const slots = await resolveSlots(tenant(), {})
    for (const s of slots.filter(s => s.state !== 'disabled')) {
      expect(s.href, `${s.kind} has no href`).toBeTruthy()
    }
  })
})

describe('(a) coordination', () => {
  it('connects when the embed is live', async () => {
    const [c] = await resolveSlots(tenant(), connectedProbes)
    expect(c.state).toBe('connected')
    expect(c.href).toContain('/embed/board')
  })

  it('falls back to a link-out when the embed is not live yet', async () => {
    // Shipping the slot before the Smarter embed exists is the point: the
    // workspace shape stops changing when the embed lands.
    const [c] = await resolveSlots(tenant({ coordination: { enabled: true, boardUrl: 'https://smarter.example/embed/board', embedLive: false } }), {})
    expect(c.state).toBe('not_connected')
    expect(c.href).toBeTruthy()
    expect(c.reason).toMatch(/link-out/)
  })

  it('degrades to link-out when the liveness probe throws', async () => {
    const [c] = await resolveSlots(tenant(), { coordinationLive: async () => { throw new Error('boom') } })
    expect(c.state).toBe('not_connected')
    expect(c.href).toBeTruthy()
  })

  it('is disabled when the tenant turned it off', async () => {
    const [c] = await resolveSlots(tenant({ coordination: { enabled: false } }), connectedProbes)
    expect(c.state).toBe('disabled')
  })
})

describe('(b) interception is default-ON', () => {
  it('an absent config means advisory, not off', async () => {
    const slots = await resolveSlots({ tenantId: 't' }, {})
    const i = slots.find(s => s.kind === 'interception')!
    expect(i.state).toBe('connected')
    expect(i.detail?.mode).toBe('advisory')
  })

  it('gate mode advertises that escalations create approval cards', async () => {
    const slots = await resolveSlots(tenant({ interception: { mode: 'gate' } }), {})
    const i = slots.find(s => s.kind === 'interception')!
    expect(i.detail?.createsCards).toBe(true)
    expect(i.href).toBe('/sign-offs')
  })

  it('advisory mode does not claim to create cards', async () => {
    const slots = await resolveSlots(tenant({ interception: { mode: 'advisory' } }), {})
    expect(slots.find(s => s.kind === 'interception')!.detail?.createsCards).toBe(false)
  })

  it('off is honoured, because a tenant that said off meant off', async () => {
    const slots = await resolveSlots(tenant({ interception: { mode: 'off' } }), {})
    expect(slots.find(s => s.kind === 'interception')!.state).toBe('disabled')
  })
})

describe('(c) compliance fails open', () => {
  it('shows findings and filings when connected', async () => {
    const slots = await resolveSlots(tenant(), connectedProbes)
    const c = slots.find(s => s.kind === 'compliance')!
    expect(c.state).toBe('connected')
    expect(c.headline).toMatch(/3 open findings/)
    expect(c.headline).toMatch(/current/)
    expect(c.href).toContain('radar')
  })

  it('singularises one finding', async () => {
    const slots = await resolveSlots(tenant(), {
      ...connectedProbes,
      compliancePull: async () => ({ openFindings: 1, filingsStatus: 'current' }),
    })
    expect(slots.find(s => s.kind === 'compliance')!.headline).toMatch(/1 open finding ·/)
  })

  it('shows "not connected" rather than blanking when Apparently is down', async () => {
    const slots = await resolveSlots(tenant(), {
      compliancePull: async () => { throw new Error('S2S timeout') },
    })
    const c = slots.find(s => s.kind === 'compliance')!
    expect(c.state).toBe('not_connected')
    expect(c.reason).toMatch(/S2S timeout/)
    expect(c.href).toBeTruthy()
  })

  it('asks the user to connect when no org is linked', async () => {
    const slots = await resolveSlots(tenant({ compliance: { enabled: true } }), connectedProbes)
    const c = slots.find(s => s.kind === 'compliance')!
    expect(c.state).toBe('not_connected')
    expect(c.reason).toMatch(/no Apparently org/)
  })
})

describe('(d) risk is link-out only', () => {
  it('offers a hedge deep-link when a quantified risk exists', async () => {
    const slots = await resolveSlots(tenant(), connectedProbes)
    const r = slots.find(s => s.kind === 'risk')!
    expect(r.state).toBe('connected')
    expect(r.headline).toMatch(/\$250,000/)
    expect(r.href).toContain('tomorrow.example/hedge')
    expect(r.href).toContain('estimate=250000')
    // No S2S execution in this pass, and the flag says so out loud.
    expect(r.detail?.linkOutOnly).toBe(true)
  })

  it('url-encodes the subject', async () => {
    const slots = await resolveSlots(tenant(), {
      ...connectedProbes,
      materialRisk: async () => ({ estimateUsd: 10, subject: 'a & b?' }),
    })
    expect(slots.find(s => s.kind === 'risk')!.href).toContain('subject=a%20%26%20b%3F')
  })

  it('says so plainly when there is no quantified risk', async () => {
    const slots = await resolveSlots(tenant(), { ...connectedProbes, materialRisk: async () => null })
    expect(slots.find(s => s.kind === 'risk')!.state).toBe('not_connected')
  })

  it('ignores a zero or negative estimate', async () => {
    for (const estimateUsd of [0, -5]) {
      const slots = await resolveSlots(tenant(), {
        ...connectedProbes, materialRisk: async () => ({ estimateUsd, subject: 'x' }),
      })
      expect(slots.find(s => s.kind === 'risk')!.state).toBe('not_connected')
    }
  })

  it('degrades rather than throwing when the probe fails', async () => {
    const slots = await resolveSlots(tenant(), {
      materialRisk: async () => { throw new Error('no data') },
    })
    const r = slots.find(s => s.kind === 'risk')!
    expect(r.state).toBe('not_connected')
    expect(r.reason).toMatch(/no data/)
  })
})

describe('resolveSlots never throws', () => {
  it('survives a null-ish config', async () => {
    const slots = await resolveSlots(null as unknown as TenantIntegrationConfig, {})
    expect(slots).toHaveLength(4)
  })

  it('survives every probe rejecting at once', async () => {
    const boom = async () => { throw new Error('everything is down') }
    const slots = await resolveSlots(tenant(), {
      coordinationLive: boom as never, compliancePull: boom as never, materialRisk: boom as never,
    })
    expect(slots).toHaveLength(4)
    expect(slots.every(s => typeof s.headline === 'string')).toBe(true)
  })
})
