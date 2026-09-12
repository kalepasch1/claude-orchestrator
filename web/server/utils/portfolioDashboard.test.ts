import { describe, expect, it } from 'vitest'
import {
  ONBOARDING_STEPS,
  buildDashboard,
  onboardingProgress,
  urgencyOf,
  type EntityFacts,
} from './portfolioDashboard'

/**
 * §2's proof line: the dashboard renders N seeded entities, and BOTH modes —
 * private cockpit and Apparently-embedded — render from the same machine.
 *
 * The tests that carry weight are the ordering ones. This screen exists to
 * answer "what do all my entities need from me right now", so an inbox that
 * ranks by anything other than urgency, or that reshuffles between renders, has
 * failed at its only job even if every field is populated correctly.
 */

const NOW = 1_787_500_000_000
const hoursAgo = (h: number) => NOW - h * 3_600_000

function seed(n: number): EntityFacts[] {
  return Array.from({ length: n }, (_, i) => ({
    entityId: `e${i}`,
    displayName: `Entity ${i}`,
    runningTasks: i,
    queuedTasks: i * 2,
    pendingApprovals: [],
  }))
}

describe('N entities render', () => {
  it('renders every seeded entity, for several N', () => {
    for (const n of [0, 1, 3, 12]) {
      const view = buildDashboard('private_cockpit', seed(n), NOW)
      expect(view.entities).toHaveLength(n)
      expect(view.totals.entities).toBe(n)
    }
  })

  it('totals fleet activity across entities', () => {
    const view = buildDashboard('private_cockpit', seed(4), NOW)
    expect(view.totals.running).toBe(0 + 1 + 2 + 3)
    expect(view.totals.queued).toBe(0 + 2 + 4 + 6)
  })

  it('an entity with no data still gets a card rather than vanishing', () => {
    // A missing entity is an entity nobody notices is stuck.
    const view = buildDashboard('private_cockpit', [{ entityId: 'x' } as EntityFacts], NOW)
    expect(view.entities).toHaveLength(1)
    expect(view.entities[0].displayName).toBe('x')
    expect(view.entities[0].compliance.state).toBe('not_connected')
    expect(view.entities[0].nextWave).toBeNull()
  })

  it('drops only entities with no id at all', () => {
    const view = buildDashboard('private_cockpit', [{} as EntityFacts, ...seed(2)], NOW)
    expect(view.entities).toHaveLength(2)
  })

  it('needsYou tracks the human being the blocker, not the fleet being busy', () => {
    const busy: EntityFacts = { entityId: 'b', displayName: 'B', runningTasks: 50, queuedTasks: 90, pendingApprovals: [] }
    const waiting: EntityFacts = {
      entityId: 'w', displayName: 'W', runningTasks: 0, queuedTasks: 0,
      pendingApprovals: [{ approvalId: 'a1', entityId: 'w', summary: 's', waitingSince: hoursAgo(1) }],
    }
    const view = buildDashboard('private_cockpit', [busy, waiting], NOW)
    expect(view.entities.find(e => e.entityId === 'b')!.needsYou).toBe(false)
    expect(view.entities.find(e => e.entityId === 'w')!.needsYou).toBe(true)
  })
})

describe('both modes render from one machine', () => {
  const entities = seed(3)

  it('private cockpit carries operator tools', () => {
    const view = buildDashboard('private_cockpit', entities, NOW)
    expect(view.mode).toBe('private_cockpit')
    expect(view.operatorTools).toBeDefined()
  })

  it('the embedded mode OMITS operator tools rather than emptying them', () => {
    // A customer-facing bundle should not even carry the shape.
    const view = buildDashboard('apparently_embedded', entities, NOW)
    expect(view.mode).toBe('apparently_embedded')
    expect('operatorTools' in view).toBe(false)
  })

  it('entity data is identical in both modes', () => {
    const a = buildDashboard('private_cockpit', entities, NOW)
    const b = buildDashboard('apparently_embedded', entities, NOW)
    expect(a.entities).toEqual(b.entities)
    expect(a.totals).toEqual(b.totals)
  })
})

describe('the cross-entity inbox is ordered by urgency', () => {
  const entities: EntityFacts[] = [
    {
      entityId: 'e1', displayName: 'One', runningTasks: 0, queuedTasks: 0,
      pendingApprovals: [
        { approvalId: 'trivial', entityId: 'e1', summary: 'copy tweak', waitingSince: hoursAgo(1) },
        { approvalId: 'expensive', entityId: 'e1', summary: 'licensing exposure', waitingSince: hoursAgo(2), estimateUsd: 250_000 },
      ],
    },
    {
      entityId: 'e2', displayName: 'Two', runningTasks: 0, queuedTasks: 0,
      pendingApprovals: [
        { approvalId: 'blocking', entityId: 'e2', summary: 'release gate', waitingSince: hoursAgo(1), blocking: true },
        { approvalId: 'stale', entityId: 'e2', summary: 'old question', waitingSince: hoursAgo(24 * 14) },
      ],
    },
  ]

  it('collects approvals from every entity', () => {
    const view = buildDashboard('private_cockpit', entities, NOW)
    expect(view.inbox).toHaveLength(4)
    expect(view.totals.pendingApprovals).toBe(4)
  })

  it('money and blocking outrank a trivial recent item', () => {
    const view = buildDashboard('private_cockpit', entities, NOW)
    const order = view.inbox.map(a => a.approvalId)
    expect(order.indexOf('expensive')).toBeLessThan(order.indexOf('trivial'))
    expect(order.indexOf('blocking')).toBeLessThan(order.indexOf('trivial'))
  })

  it('a two-week-old item outranks a one-hour-old one of equal weight', () => {
    const view = buildDashboard('private_cockpit', entities, NOW)
    const order = view.inbox.map(a => a.approvalId)
    expect(order.indexOf('stale')).toBeLessThan(order.indexOf('trivial'))
  })

  it('but age alone does not drown a large exposure', () => {
    // Log growth on waiting is what keeps a month-old nit from owning the top.
    const view = buildDashboard('private_cockpit', entities, NOW)
    const order = view.inbox.map(a => a.approvalId)
    expect(order.indexOf('expensive')).toBeLessThan(order.indexOf('stale'))
  })

  it('the order is stable across renders', () => {
    const a = buildDashboard('private_cockpit', entities, NOW).inbox.map(x => x.approvalId)
    const b = buildDashboard('private_cockpit', entities, NOW).inbox.map(x => x.approvalId)
    expect(a).toEqual(b)
  })

  it('ties break deterministically by id, not by insertion order', () => {
    const tied: EntityFacts[] = [{
      entityId: 'e', displayName: 'E', runningTasks: 0, queuedTasks: 0,
      pendingApprovals: [
        { approvalId: 'zzz', entityId: 'e', summary: 's', waitingSince: hoursAgo(3) },
        { approvalId: 'aaa', entityId: 'e', summary: 's', waitingSince: hoursAgo(3) },
      ],
    }]
    expect(buildDashboard('private_cockpit', tied, NOW).inbox.map(a => a.approvalId)).toEqual(['aaa', 'zzz'])
  })

  it('every inbox item explains itself in words', () => {
    const view = buildDashboard('private_cockpit', entities, NOW)
    for (const item of view.inbox) {
      expect(item.rationale.length).toBeGreaterThan(0)
    }
    const expensive = view.inbox.find(a => a.approvalId === 'expensive')!
    expect(expensive.rationale).toMatch(/\$250,000 at stake/)
    const blocking = view.inbox.find(a => a.approvalId === 'blocking')!
    expect(blocking.rationale).toMatch(/blocking a release/)
  })

  it('inherits the entity id when an approval omits it', () => {
    const view = buildDashboard('private_cockpit', [{
      entityId: 'owner', displayName: 'O', runningTasks: 0, queuedTasks: 0,
      pendingApprovals: [{ approvalId: 'a', entityId: '', summary: 's', waitingSince: NOW }],
    }], NOW)
    expect(view.inbox[0].entityId).toBe('owner')
  })
})

describe('urgencyOf', () => {
  it('is zero for a brand-new, unquantified, non-blocking item', () => {
    expect(urgencyOf({ approvalId: 'a', entityId: 'e', summary: 's', waitingSince: NOW }, NOW).urgency).toBe(0)
  })

  it('never goes negative on a future timestamp', () => {
    const r = urgencyOf({ approvalId: 'a', entityId: 'e', summary: 's', waitingSince: NOW + 999_999 }, NOW)
    expect(r.urgency).toBeGreaterThanOrEqual(0)
    expect(r.waitingHours).toBe(0)
  })

  it('ignores a negative or non-numeric estimate', () => {
    for (const estimateUsd of [-5, NaN, 'lots' as unknown as number]) {
      const r = urgencyOf({ approvalId: 'a', entityId: 'e', summary: 's', waitingSince: NOW, estimateUsd }, NOW)
      expect(r.urgency).toBe(0)
    }
  })
})

describe('buildDashboard never throws', () => {
  it('survives null, undefined and junk', () => {
    for (const junk of [null, undefined, 'entities' as unknown, 42 as unknown]) {
      const view = buildDashboard('private_cockpit', junk as never, NOW)
      expect(view.entities).toEqual([])
      expect(view.inbox).toEqual([])
    }
  })
})

describe('onboarding', () => {
  const full = {
    githubInstalled: true, selectedRepos: ['org/repo'], deployTarget: 'vercel',
    projects: ['p1'], constitutionTemplate: 'conservative', firstOutcomeSubmitted: true,
  }

  it('walks the fixed order and gates each step on the last', () => {
    expect(onboardingProgress({}).step).toBe('connect_github')
    expect(onboardingProgress({ githubInstalled: true, selectedRepos: ['org/repo'] }).step).toBe('connect_deploy_target')
    expect(onboardingProgress({ ...full, projects: [], constitutionTemplate: undefined, firstOutcomeSubmitted: false }).step).toBe('register_projects')
    expect(onboardingProgress({ ...full, constitutionTemplate: undefined, firstOutcomeSubmitted: false }).step).toBe('declare_constitution')
    expect(onboardingProgress({ ...full, firstOutcomeSubmitted: false }).step).toBe('first_outcome')
    expect(onboardingProgress(full).step).toBe('complete')
  })

  it('github installed with no repo selected is not done', () => {
    expect(onboardingProgress({ githubInstalled: true, selectedRepos: [] }).step).toBe('connect_github')
  })

  it('supabase is genuinely optional and never blocks', () => {
    const withoutSupabase = onboardingProgress(full)
    const withSupabase = onboardingProgress({ ...full, supabaseRef: 'abc' })
    expect(withoutSupabase.step).toBe('complete')
    expect(withSupabase.step).toBe('complete')
  })

  it('every blocked step says what is missing', () => {
    for (const state of [{}, { githubInstalled: true, selectedRepos: ['r'] }, { ...full, firstOutcomeSubmitted: false }]) {
      const p = onboardingProgress(state)
      expect(p.blockedBy && p.blockedBy.length).toBeTruthy()
    }
  })

  it('records that there is NO self-serve billing for Madeus', () => {
    // In the data, so a future UI cannot quietly add a billing step.
    expect(onboardingProgress(full).selfServeBilling).toBe(false)
    expect(onboardingProgress({}).selfServeBilling).toBe(false)
    expect(ONBOARDING_STEPS).not.toContain('billing' as never)
  })

  it('handles null state', () => {
    expect(onboardingProgress(null).step).toBe('connect_github')
  })
})
