import { describe, expect, it } from 'vitest'

import {
  accountableOfficer,
  assessFiling,
  filingSchedule,
  isBusinessDay,
  nextDueDate,
  previousDueDate,
  regulatorFeed,
  regulatorFeedRecord,
  rollDueDate,
  unownedFilings,
  type FilingSpec,
} from '../../../shared/contracts/filings-as-code'

const OFFICER = {
  id: 'off-1',
  name: 'A. Officer',
  role: 'Chief Compliance Officer',
  email: 'officer@example.com',
}

/** A prior-period filing on record, so specs under test are not all "overdue". */
const FILED = '2025-04-01'

const annual = (over: Partial<FilingSpec> = {}): FilingSpec => ({
  id: 'nv-annual',
  authority: 'Nevada Gaming Control Board',
  jurisdiction: 'US-NV',
  form: 'Annual Report',
  cadence: 'annual',
  dueMonth: 3,
  dueDay: 15,
  accountableOfficer: OFFICER,
  ...over,
})

describe('§2 deadline omniscience', () => {
  it('computes the next annual due date strictly after the reference date', () => {
    const due = nextDueDate(annual(), '2026-01-10T00:00:00Z')
    expect(due?.toISOString().slice(0, 10)).toBe('2026-03-16') // 15th is a Sunday
  })

  it('rolls past the due date to the following year once it has passed', () => {
    const due = nextDueDate(annual(), '2026-04-01T00:00:00Z')
    expect(due?.getUTCFullYear()).toBe(2027)
  })

  it('rolls a weekend due date to the next business day by default', () => {
    // 2026-08-15 is a Saturday.
    const due = nextDueDate(annual({ dueMonth: 8, dueDay: 15 }), '2026-08-01T00:00:00Z')
    expect(due?.toISOString().slice(0, 10)).toBe('2026-08-17')
  })

  it('honours a previous_business_day roll', () => {
    const due = nextDueDate(
      annual({ dueMonth: 8, dueDay: 15, roll: 'previous_business_day' }),
      '2026-08-01T00:00:00Z',
    )
    expect(due?.toISOString().slice(0, 10)).toBe('2026-08-14')
  })

  it('leaves an exact-roll deadline on the weekend', () => {
    const due = nextDueDate(annual({ dueMonth: 8, dueDay: 15, roll: 'exact' }),
      '2026-08-01T00:00:00Z')
    expect(due?.toISOString().slice(0, 10)).toBe('2026-08-15')
  })

  it('treats a declared authority holiday as a non-business day', () => {
    expect(isBusinessDay(new Date('2026-08-17T00:00:00Z'), ['2026-08-17'])).toBe(false)
    const due = nextDueDate(
      annual({ dueMonth: 8, dueDay: 15, holidays: ['2026-08-17'] }),
      '2026-08-01T00:00:00Z',
    )
    expect(due?.toISOString().slice(0, 10)).toBe('2026-08-18')
  })

  it('clamps day 31 into a short month rather than rolling into the next one', () => {
    // Rolling would move the deadline a month later and read as "plenty of
    // time" when the filing is in fact imminent.
    const due = nextDueDate(annual({ dueMonth: 2, dueDay: 31, roll: 'exact' }),
      '2026-01-01T00:00:00Z')
    expect(due?.getUTCMonth()).toBe(1)
    expect(due?.getUTCDate()).toBe(28)
  })

  it('produces a quarterly schedule three months apart', () => {
    const dates = filingSchedule(
      annual({ id: 'q', cadence: 'quarterly', dueMonth: undefined, dueDay: 20 }),
      '2026-01-01T00:00:00Z', 4)
    expect(dates).toHaveLength(4)
    for (let i = 1; i < dates.length; i += 1) {
      expect(dates[i]!.getTime()).toBeGreaterThan(dates[i - 1]!.getTime())
    }
  })

  it('refuses to invent a schedule for one_time and event_driven filings', () => {
    expect(nextDueDate(annual({ cadence: 'one_time' }), '2026-01-01T00:00:00Z')).toBeNull()
    expect(nextDueDate(annual({ cadence: 'event_driven' }), '2026-01-01T00:00:00Z')).toBeNull()
    expect(filingSchedule(annual({ cadence: 'one_time' }), '2026-01-01T00:00:00Z')).toEqual([])
  })

  it('returns null rather than a plausible date for a malformed spec', () => {
    expect(nextDueDate(annual({ dueDay: 0 }), '2026-01-01T00:00:00Z')).toBeNull()
    expect(nextDueDate(annual({ dueDay: 99 }), '2026-01-01T00:00:00Z')).toBeNull()
    expect(nextDueDate(annual({ dueMonth: 13 }), '2026-01-01T00:00:00Z')).toBeNull()
    expect(nextDueDate(annual(), 'not-a-date')).toBeNull()
  })

  it('bounds the roll search so a pathological holiday list cannot hang', () => {
    const everyDay = Array.from({ length: 30 }, (_, i) =>
      new Date(Date.UTC(2026, 7, i + 1)).toISOString().slice(0, 10))
    expect(rollDueDate(new Date('2026-08-03T00:00:00Z'), 'next_business_day', everyDay)).toBeNull()
  })
})

describe('§3 status and urgency', () => {
  it('previousDueDate finds the period that has already come due', () => {
    const prev = previousDueDate(annual({ roll: 'exact' }), '2026-03-20T00:00:00Z')
    expect(prev?.toISOString().slice(0, 10)).toBe('2026-03-15')
  })

  it('reports overdue against the period that already passed', () => {
    // Regression: assessing only the NEXT due date reported a filing that blew
    // its deadline five days ago as "not yet open" — the most dangerous answer
    // a compliance calendar can give. previousDueDate is what makes 'overdue'
    // reachable at all.
    const a = assessFiling(annual({ roll: 'exact' }), '2026-03-20T00:00:00Z')
    expect(a.status).toBe('overdue')
    expect(a.daysUntilDue).toBe(-5)
    expect(a.dueDate).toBe('2026-03-15')
    expect(a.actionRequired).toBe(true)
  })

  it('treats "no filing on record" as overdue, not as filed', () => {
    // "we have no record" and "it was filed" must not collapse into the same
    // reassuring answer.
    expect(assessFiling(annual({ roll: 'exact' }), '2026-06-01T00:00:00Z').status)
      .toBe('overdue')
  })

  it('reports due_soon inside the warning window', () => {
    const a = assessFiling(
      annual({ warnDaysBefore: 20, roll: 'exact', lastFiledAt: FILED }),
      '2026-03-05T00:00:00Z')
    expect(a.status).toBe('due_soon')
    expect(a.daysUntilDue).toBe(10)
    expect(a.actionRequired).toBe(true)
  })

  it('reports open inside the filing window without demanding action', () => {
    const a = assessFiling(
      annual({ warnDaysBefore: 5, opensDaysBefore: 60, roll: 'exact', lastFiledAt: FILED }),
      '2026-02-01T00:00:00Z')
    expect(a.status).toBe('open')
    expect(a.actionRequired).toBe(false)
  })

  it('reports filed when the due period is satisfied and the next has not opened', () => {
    const a = assessFiling(annual({ lastFiledAt: FILED }), '2026-01-10T00:00:00Z')
    expect(a.status).toBe('filed')
    expect(a.actionRequired).toBe(false)
  })

  it('does not let filed shadow an open window', () => {
    // Once the window is open, "go file it" is the useful signal, not "you
    // filed last time".
    const a = assessFiling(
      annual({ opensDaysBefore: 90, warnDaysBefore: 5, roll: 'exact', lastFiledAt: FILED }),
      '2026-02-01T00:00:00Z')
    expect(a.status).toBe('open')
  })

  it('an unevaluable filing requires action rather than disappearing', () => {
    const a = assessFiling(annual({ cadence: 'event_driven' }), '2026-01-01T00:00:00Z')
    expect(a.status).toBe('unknown')
    expect(a.actionRequired).toBe(true)
  })

  it('an unowned filing always requires action, whatever the date says', () => {
    const a = assessFiling(
      annual({ accountableOfficer: null, opensDaysBefore: 1, roll: 'exact', lastFiledAt: FILED }),
      '2026-01-01T00:00:00Z')
    expect(a.actionRequired).toBe(true)
    expect(a.reasons.join(' ')).toContain('NO ACCOUNTABLE OFFICER')
  })

  it('names the ownership gap even on the overdue path', () => {
    const a = assessFiling(annual({ accountableOfficer: null, roll: 'exact' }),
      '2026-03-20T00:00:00Z')
    expect(a.status).toBe('overdue')
    expect(a.reasons.join(' ')).toContain('NO ACCOUNTABLE OFFICER')
  })

  it('never throws on malformed input', () => {
    // @ts-expect-error deliberately malformed
    const a = assessFiling(null, 'nonsense')
    expect(a.status).toBe('unknown')
    expect(a.actionRequired).toBe(true)
  })
})

describe('§4 accountability', () => {
  it('accepts a complete officer', () => {
    expect(accountableOfficer(annual())?.id).toBe('off-1')
  })

  it('rejects a partially specified officer', () => {
    // Half a contact record creates the appearance of ownership without the
    // substance, which suppresses the alarm.
    for (const missing of ['id', 'name', 'role', 'email'] as const) {
      const officer = { ...OFFICER, [missing]: '  ' }
      expect(accountableOfficer(annual({ accountableOfficer: officer }))).toBeNull()
    }
  })

  it('rejects an email that cannot be delivered to', () => {
    const officer = { ...OFFICER, email: 'not-an-address' }
    expect(accountableOfficer(annual({ accountableOfficer: officer }))).toBeNull()
  })

  it('lists every filing nobody is answerable for', () => {
    const owned = annual({ id: 'owned' })
    const orphan = annual({ id: 'orphan', accountableOfficer: null })
    expect(unownedFilings([owned, orphan]).map((s) => s.id)).toEqual(['orphan'])
  })
})

describe('§5 regulator feed', () => {
  it('normalises an assessment into the feed shape', () => {
    const record = regulatorFeedRecord(annual({ lastFiledAt: FILED }), '2026-01-10T00:00:00Z')
    expect(record).toMatchObject({
      specId: 'nv-annual',
      authority: 'Nevada Gaming Control Board',
      jurisdiction: 'US-NV',
      cadence: 'annual',
      accountableOfficerId: 'off-1',
    })
  })

  it('orders the most urgent obligation first', () => {
    const specs = [
      annual({ id: 'far', dueMonth: 12, dueDay: 1, opensDaysBefore: 5, warnDaysBefore: 2,
        roll: 'exact', lastFiledAt: '2025-12-02' }),
      annual({ id: 'overdue', dueMonth: 1, dueDay: 5, roll: 'exact' }),
      annual({ id: 'soon', dueMonth: 3, dueDay: 5, warnDaysBefore: 30, roll: 'exact',
        lastFiledAt: '2025-03-06' }),
      annual({ id: 'unknown', cadence: 'event_driven' }),
    ]
    const feed = regulatorFeed(specs, '2026-03-01T00:00:00Z')
    expect(feed.map((r) => r.specId)).toEqual(['overdue', 'unknown', 'soon', 'far'])
  })

  it('returns an empty feed for empty input rather than throwing', () => {
    expect(regulatorFeed([], '2026-01-01T00:00:00Z')).toEqual([])
    // @ts-expect-error deliberately malformed
    expect(regulatorFeed(null, '2026-01-01T00:00:00Z')).toEqual([])
  })
})
