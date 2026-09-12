import { describe, expect, it } from 'vitest'
import {
  EMBED_PROTOCOL_VERSION,
  EMBED_SURFACES,
  authorizeEmbed,
  hashKey,
  makeEnvelope,
  parseEnvelope,
  validateApprovalDecision,
  validateOutcome,
  type EmbedKeyRecord,
} from './embedProtocol'

/**
 * The embed SDK's contract, tested from the outside a hostile host would see.
 *
 * The happy path is nearly uninteresting. What matters is that every DENY is a
 * deny: a key from the wrong origin, a key for a surface it was not granted, a
 * revoked key, a payload that tries to name its own tenant, and a decision with
 * no decider. Each of those is a real way to lose tenant isolation.
 */

const KEY = 'mk_live_abcdef0123456789'
const OTHER_KEY = 'mk_live_zzzzzzzzzzzzzzzz'

function records(overrides: Partial<EmbedKeyRecord> = {}): EmbedKeyRecord[] {
  return [{
    tenantId: 'tenant-a',
    keyHash: hashKey(KEY),
    allowedOrigins: ['https://apparently.cc'],
    surfaces: ['strip', 'universal_command'],
    ...overrides,
  }]
}

describe('authorizeEmbed', () => {
  it('accepts a good key from an allow-listed origin for a granted surface', () => {
    const r = authorizeEmbed(KEY, 'https://apparently.cc', 'universal_command', records())
    expect(r.ok).toBe(true)
    expect(r.tenantId).toBe('tenant-a')
  })

  it('normalises origin casing and a trailing slash', () => {
    expect(authorizeEmbed(KEY, 'https://APPARENTLY.cc/', 'strip', records()).ok).toBe(true)
  })

  it('rejects an unknown key', () => {
    const r = authorizeEmbed(OTHER_KEY, 'https://apparently.cc', 'strip', records())
    expect(r.ok).toBe(false)
    expect(r.reason).toMatch(/unknown embed key/)
  })

  it('rejects a missing key', () => {
    expect(authorizeEmbed(undefined, 'https://apparently.cc', 'strip', records()).ok).toBe(false)
  })

  it('rejects a revoked key without revealing its surfaces', () => {
    const r = authorizeEmbed(KEY, 'https://apparently.cc', 'strip', records({ revoked: true }))
    expect(r.ok).toBe(false)
    expect(r.reason).toMatch(/revoked/)
    expect(r.reason).not.toMatch(/surface/)
  })

  it('rejects a good key presented from an origin the tenant never declared', () => {
    // The leaked-key case: binding to origin turns a total compromise into a
    // narrow one, and this is the assertion that keeps that true.
    const r = authorizeEmbed(KEY, 'https://evil.example', 'strip', records())
    expect(r.ok).toBe(false)
    expect(r.reason).toMatch(/not allow-listed/)
  })

  it('rejects when no origin is supplied at all', () => {
    expect(authorizeEmbed(KEY, undefined, 'strip', records()).ok).toBe(false)
  })

  it('treats an empty origin list as unusable, not as open', () => {
    const r = authorizeEmbed(KEY, 'https://apparently.cc', 'strip', records({ allowedOrigins: [] }))
    expect(r.ok).toBe(false)
    expect(r.reason).toMatch(/no allowed origins/)
  })

  it('treats an empty surface list as unusable, not as all', () => {
    const r = authorizeEmbed(KEY, 'https://apparently.cc', 'strip', records({ surfaces: [] }))
    expect(r.ok).toBe(false)
    expect(r.reason).toMatch(/not granted/)
  })

  it('rejects a surface the key does not hold', () => {
    const r = authorizeEmbed(KEY, 'https://apparently.cc', 'tenancy_admin', records())
    expect(r.ok).toBe(false)
    expect(r.reason).toMatch(/not granted/)
  })

  it('rejects an unknown surface name', () => {
    expect(authorizeEmbed(KEY, 'https://apparently.cc', 'root_shell', records()).ok).toBe(false)
  })

  it('never returns another tenant', () => {
    const two = [...records(), {
      tenantId: 'tenant-b', keyHash: hashKey(OTHER_KEY),
      allowedOrigins: ['https://apparently.cc'], surfaces: ['strip'] as const,
    }]
    expect(authorizeEmbed(KEY, 'https://apparently.cc', 'strip', two).tenantId).toBe('tenant-a')
    expect(authorizeEmbed(OTHER_KEY, 'https://apparently.cc', 'strip', two).tenantId).toBe('tenant-b')
  })

  it('does not store or echo the raw key', () => {
    expect(hashKey(KEY)).not.toContain(KEY)
    expect(hashKey(KEY)).toMatch(/^[a-f0-9]{64}$/)
    expect(JSON.stringify(authorizeEmbed(KEY, 'https://apparently.cc', 'strip', records())))
      .not.toContain(KEY)
  })
})

describe('envelope', () => {
  it('round-trips', () => {
    const env = makeEnvelope('embed_to_host', 'outcome.submit', 'tenant-a', 'universal_command', { outcome: 'x' }, 'c-1', 1000)
    const parsed = parseEnvelope(env)
    expect(parsed.ok).toBe(true)
    if (parsed.ok) expect(parsed.envelope.correlationId).toBe('c-1')
  })

  it('rejects a stale protocol version with a readable reason', () => {
    const env = { ...makeEnvelope('host_to_embed', 'x', 't', 'strip', {}), v: 0 }
    const parsed = parseEnvelope(env)
    expect(parsed.ok).toBe(false)
    if (!parsed.ok) expect(parsed.reason).toMatch(/unsupported protocol version/)
  })

  it('rejects missing or malformed fields, each with its own reason', () => {
    const base = makeEnvelope('host_to_embed', 'x', 't', 'strip', {})
    const cases: Array<[Record<string, unknown>, RegExp]> = [
      [{ ...base, direction: 'sideways' }, /direction/],
      [{ ...base, kind: '' }, /kind/],
      [{ ...base, tenantId: '' }, /tenantId/],
      [{ ...base, surface: 'nope' }, /unknown surface/],
      [{ ...base, sentAt: 'now' }, /sentAt/],
    ]
    for (const [bad, re] of cases) {
      const parsed = parseEnvelope(bad)
      expect(parsed.ok).toBe(false)
      if (!parsed.ok) expect(parsed.reason).toMatch(re)
    }
  })

  it('rejects non-objects', () => {
    for (const junk of [null, undefined, 'hi', 42, []]) {
      expect(parseEnvelope(junk as unknown).ok).toBe(junk === null ? false : false)
    }
  })

  it('exposes every surface the contract names', () => {
    expect(EMBED_SURFACES).toContain('strip')
    expect(EMBED_SURFACES).toContain('department_fleet_init')
    expect(EMBED_PROTOCOL_VERSION).toBe(1)
  })
})

describe('validateOutcome', () => {
  it('takes the tenant from auth, never from the payload', () => {
    // A host that could name its own tenant could name someone else's.
    const r = validateOutcome({ outcome: 'ship it', hostApp: 'apparently', tenantId: 'tenant-b' }, 'tenant-a')
    expect(r.ok).toBe(true)
    if (r.ok) expect(r.submission.tenantId).toBe('tenant-a')
  })

  it('requires outcome text and hostApp', () => {
    expect(validateOutcome({ hostApp: 'apparently' }, 't').ok).toBe(false)
    expect(validateOutcome({ outcome: '  ' }, 't').ok).toBe(false)
    expect(validateOutcome({ outcome: 'x' }, 't').ok).toBe(false)
  })

  it('bounds the outcome length', () => {
    expect(validateOutcome({ outcome: 'x'.repeat(8001), hostApp: 'a' }, 't').ok).toBe(false)
  })

  it('carries optional entity and department through', () => {
    const r = validateOutcome({ outcome: 'x', hostApp: 'pareto', entityId: 'e1', department: 'legal' }, 't')
    expect(r.ok).toBe(true)
    if (r.ok) expect(r.submission.department).toBe('legal')
  })
})

describe('validateApprovalDecision', () => {
  it('accepts a fully attributed decision', () => {
    const r = validateApprovalDecision({
      approvalId: 'a-1', decision: 'approved', decidedBy: 'u-9',
      decidedByLabel: 'Counsel', rationale: 'fine', hostApp: 'smarter',
    })
    expect(r.ok).toBe(true)
  })

  it('refuses a decision with no decider', () => {
    const r = validateApprovalDecision({ approvalId: 'a-1', decision: 'approved', hostApp: 'smarter' })
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.reason).toMatch(/decidedBy/)
  })

  it('refuses an invalid verdict', () => {
    expect(validateApprovalDecision({ approvalId: 'a', decision: 'maybe', decidedBy: 'u', hostApp: 'h' }).ok).toBe(false)
  })

  it('refuses a decision with no host', () => {
    expect(validateApprovalDecision({ approvalId: 'a', decision: 'approved', decidedBy: 'u' }).ok).toBe(false)
  })

  it('bounds the rationale', () => {
    const r = validateApprovalDecision({
      approvalId: 'a', decision: 'rejected', decidedBy: 'u', hostApp: 'h',
      rationale: 'x'.repeat(5000),
    })
    expect(r.ok).toBe(true)
    if (r.ok) expect(r.decision.rationale?.length).toBe(4000)
  })
})
