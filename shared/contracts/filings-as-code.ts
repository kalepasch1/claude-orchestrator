/**
 * Filings-as-Code — SHARED CONTRACT.
 *
 * A regulatory filing obligation stated as data, not as prose in a runbook and a
 * reminder in someone's calendar. Every consumer (deadline omniscience, the
 * regulator data feed, the filing agent) reads the SAME FilingSpec, so a rule
 * change is a change to one record rather than to three implementations that
 * quietly disagree about when something is due.
 *
 *   §1 FilingSpec              — the obligation, expressed once
 *   §2 nextDueDate / schedule  — deadline omniscience, business-day aware
 *   §3 assessFiling            — status + urgency for a given "now"
 *   §4 accountableOfficer      — who is answerable; fail-closed, never guessed
 *   §5 regulatorFeedRecord     — the normalised shape the regulator data feed emits
 *
 * Nothing here performs I/O or reads the clock. Every function is pure and
 * total: bad input yields a denial or an empty result, never a throw. A missed
 * filing is a regulatory event, so this module never silently produces a
 * plausible-looking answer from bad data — it produces an explicit refusal.
 */

// ─── §1 The obligation, expressed once ───────────────────────────────────────

export type FilingCadence =
  | 'annual'
  | 'semiannual'
  | 'quarterly'
  | 'monthly'
  | 'one_time'
  | 'event_driven'

/** How a due date lands when it falls on a non-business day. */
export type DueDateRoll = 'next_business_day' | 'previous_business_day' | 'exact'

export type FilingStatus =
  | 'not_yet_open'
  | 'open'
  | 'due_soon'
  | 'overdue'
  | 'filed'
  | 'unknown'

export interface AccountableOfficer {
  /** stable identifier for the person answerable for this filing */
  id: string
  name: string
  role: string
  /** an officer must be reachable, or they are not in practice accountable */
  email: string
}

export interface FilingSpec {
  id: string
  /** the regulator or authority the filing is made to */
  authority: string
  /** jurisdiction code, e.g. 'US-NV', 'US-NJ' */
  jurisdiction: string
  /** human name of the form/return */
  form: string
  cadence: FilingCadence
  /**
   * Day of the period on which the filing is due, 1-indexed. For 'annual' this
   * is the day of `dueMonth`; for quarterly/monthly it is the day of the month
   * following period end.
   */
  dueDay: number
  /** 1-12, required for annual/semiannual cadences */
  dueMonth?: number
  /** days before the due date at which the window opens */
  opensDaysBefore?: number
  /** days before the due date at which this becomes 'due_soon' */
  warnDaysBefore?: number
  roll?: DueDateRoll
  accountableOfficer?: AccountableOfficer | null
  /** ISO dates of authority holidays that are not business days */
  holidays?: string[]
  /**
   * ISO date the filing was last made. Absent means NO EVIDENCE OF FILING, and
   * a period that has already come due with no evidence is reported overdue —
   * "we have no record" and "it was filed" must not collapse into the same
   * reassuring answer.
   */
  lastFiledAt?: string | null
}

// ─── §2 Deadline omniscience ─────────────────────────────────────────────────

const DAY_MS = 86_400_000

const DEFAULT_WARN_DAYS = 14
const DEFAULT_OPENS_DAYS = 45

function isValidDate(d: Date): boolean {
  return d instanceof Date && !Number.isNaN(d.getTime())
}

function parseUtc(value: string | Date | undefined | null): Date | null {
  if (!value) return null
  const d = value instanceof Date ? new Date(value.getTime()) : new Date(`${value}`)
  return isValidDate(d) ? d : null
}

function toIsoDate(d: Date): string {
  return d.toISOString().slice(0, 10)
}

/** Saturday/Sunday or a declared authority holiday. */
export function isBusinessDay(date: Date, holidays: string[] = []): boolean {
  if (!isValidDate(date)) return false
  const day = date.getUTCDay()
  if (day === 0 || day === 6) return false
  return !holidays.includes(toIsoDate(date))
}

/**
 * Apply the roll convention. Bounded to 14 iterations so a pathological holiday
 * list cannot spin forever — a filing calendar with 14 consecutive non-business
 * days is a data error, and looping on it would hide that.
 */
export function rollDueDate(
  date: Date,
  roll: DueDateRoll = 'next_business_day',
  holidays: string[] = [],
): Date | null {
  if (!isValidDate(date)) return null
  if (roll === 'exact') return date
  const step = roll === 'previous_business_day' ? -DAY_MS : DAY_MS
  let candidate = new Date(date.getTime())
  for (let i = 0; i < 14; i += 1) {
    if (isBusinessDay(candidate, holidays)) return candidate
    candidate = new Date(candidate.getTime() + step)
  }
  return null
}

function clampDayOfMonth(year: number, monthIndex: number, day: number): Date {
  // Day 31 in a 30-day month must land on the 30th, not silently roll into the
  // next month — rolling would move the deadline a month later and read as
  // "plenty of time" when the filing is in fact imminent.
  const lastDay = new Date(Date.UTC(year, monthIndex + 1, 0)).getUTCDate()
  return new Date(Date.UTC(year, monthIndex, Math.min(Math.max(1, day), lastDay)))
}

function cadenceMonths(cadence: FilingCadence): number | null {
  switch (cadence) {
    case 'annual':
      return 12
    case 'semiannual':
      return 6
    case 'quarterly':
      return 3
    case 'monthly':
      return 1
    default:
      return null
  }
}

/**
 * The next due date strictly after `after`, or null when the cadence has no
 * computable schedule ('one_time', 'event_driven') or the spec is malformed.
 *
 * Returning null is deliberate. A one-time or event-driven filing has no next
 * date to compute, and inventing one would put a fictional deadline on a
 * compliance calendar.
 */
export function nextDueDate(spec: FilingSpec, after: Date | string): Date | null {
  const from = parseUtc(after)
  if (!from || !spec) return null

  const months = cadenceMonths(spec.cadence)
  if (months === null) return null

  const day = Number(spec.dueDay)
  if (!Number.isFinite(day) || day < 1 || day > 31) return null

  const anchorMonth = months === 12 || months === 6 ? Number(spec.dueMonth) : null
  if (months === 12 && (!Number.isFinite(anchorMonth as number) ||
      (anchorMonth as number) < 1 || (anchorMonth as number) > 12)) {
    return null
  }

  const roll = spec.roll ?? 'next_business_day'
  const holidays = spec.holidays ?? []

  // Walk candidate periods forward from a point safely before `from`.
  const startMonthIndex = anchorMonth !== null && Number.isFinite(anchorMonth)
    ? (anchorMonth as number) - 1
    : from.getUTCMonth()
  let year = from.getUTCFullYear() - 1

  for (let i = 0; i < 64; i += 1) {
    const monthOffset = startMonthIndex + i * months
    const candidateYear = year + Math.floor(monthOffset / 12)
    const candidateMonth = ((monthOffset % 12) + 12) % 12
    const raw = clampDayOfMonth(candidateYear, candidateMonth, day)
    const rolled = rollDueDate(raw, roll, holidays)
    if (rolled && rolled.getTime() > from.getTime()) return rolled
  }
  return null
}

/**
 * The most recent due date at or before `at`, or null when none has occurred.
 *
 * This is what makes 'overdue' reachable at all. Looking only forward
 * (nextDueDate) means a filing that blew its deadline yesterday reports as the
 * NEXT period's date and reads "not yet open" — the single most dangerous
 * possible answer from a compliance calendar.
 */
export function previousDueDate(spec: FilingSpec, at: Date | string): Date | null {
  const now = parseUtc(at)
  if (!now || !spec) return null
  if (cadenceMonths(spec.cadence) === null) return null

  // Walk back from a point safely before `now` and keep the latest date that
  // has already passed.
  const lookback = new Date(now.getTime() - 400 * DAY_MS)
  let cursor: Date | null = lookback
  let latest: Date | null = null
  for (let i = 0; i < 64; i += 1) {
    const next: Date | null = nextDueDate(spec, cursor as Date)
    if (!next || next.getTime() > now.getTime()) break
    latest = next
    cursor = next
  }
  return latest
}

/** The next `count` due dates. Empty when the cadence has no schedule. */
export function filingSchedule(
  spec: FilingSpec,
  after: Date | string,
  count = 4,
): Date[] {
  const out: Date[] = []
  let cursor = parseUtc(after)
  if (!cursor) return out
  for (let i = 0; i < Math.max(0, count); i += 1) {
    const next = nextDueDate(spec, cursor)
    if (!next) break
    out.push(next)
    cursor = next
  }
  return out
}

// ─── §3 Status + urgency ─────────────────────────────────────────────────────

export interface FilingAssessment {
  specId: string
  dueDate: string | null
  status: FilingStatus
  daysUntilDue: number | null
  /** true when this filing needs a human to look at it now */
  actionRequired: boolean
  accountableOfficerId: string | null
  reasons: string[]
}

export function daysBetween(a: Date, b: Date): number {
  return Math.round((b.getTime() - a.getTime()) / DAY_MS)
}

/**
 * Assess a filing against a supplied `now`. Never reads the clock itself, so
 * the same inputs always produce the same assessment and a test can pin a date.
 */
export function assessFiling(
  spec: FilingSpec,
  now: Date | string,
  filedFor?: Date | string | null,
): FilingAssessment {
  const reasons: string[] = []
  const at = parseUtc(now)

  if (!spec || !spec.id || !at) {
    return {
      specId: spec?.id ?? '',
      dueDate: null,
      status: 'unknown',
      daysUntilDue: null,
      // Unknown is NOT benign: an obligation we cannot evaluate is one a human
      // must look at, not one to be quietly filtered out of the calendar.
      actionRequired: true,
      accountableOfficerId: accountableOfficer(spec)?.id ?? null,
      reasons: ['filing could not be evaluated: malformed spec or date'],
    }
  }

  const due = nextDueDate(spec, at)
  const officer = accountableOfficer(spec)

  if (!due) {
    return {
      specId: spec.id,
      dueDate: null,
      status: 'unknown',
      daysUntilDue: null,
      actionRequired: true,
      accountableOfficerId: officer?.id ?? null,
      reasons: [`no computable schedule for cadence '${spec.cadence}'`],
    }
  }

  const filed = parseUtc(filedFor ?? spec.lastFiledAt ?? null)
  const previous = previousDueDate(spec, at)

  // OVERDUE IS CHECKED FIRST, against the period that has already come due.
  // Evaluating only the next date would report a filing that blew its deadline
  // yesterday as the NEXT period's date — "not yet open" — which is the single
  // most dangerous answer a compliance calendar can give.
  if (previous && (!filed || filed.getTime() < previous.getTime())) {
    const late = daysBetween(previous, at)
    reasons.push(`overdue by ${late} day(s); due ${toIsoDate(previous)} and no filing recorded`)
    if (!officer) reasons.push('NO ACCOUNTABLE OFFICER: nobody is answerable for this filing')
    return {
      specId: spec.id,
      dueDate: toIsoDate(previous),
      status: 'overdue',
      daysUntilDue: -late,
      actionRequired: true,
      accountableOfficerId: officer?.id ?? null,
      reasons,
    }
  }

  const days = daysBetween(at, due)
  const warn = Number.isFinite(spec.warnDaysBefore as number)
    ? (spec.warnDaysBefore as number)
    : DEFAULT_WARN_DAYS
  const opens = Number.isFinite(spec.opensDaysBefore as number)
    ? (spec.opensDaysBefore as number)
    : DEFAULT_OPENS_DAYS

  let status: FilingStatus
  if (filed && previous && filed.getTime() >= previous.getTime() && days > opens) {
    // The period that came due has been satisfied and the NEXT window has not
    // opened yet. Gated on `opens` rather than `warn` so 'filed' cannot shadow
    // 'open' — once the window is open, "go file it" is the useful signal, not
    // "you filed last time".
    status = 'filed'
    reasons.push(`filed for the period due ${toIsoDate(previous)}; next due in ${days} day(s)`)
  } else if (days <= warn) {
    status = 'due_soon'
    reasons.push(`due in ${days} day(s), inside the ${warn}-day warning window`)
  } else if (days <= opens) {
    status = 'open'
    reasons.push(`filing window open, ${days} day(s) remaining`)
  } else {
    status = 'not_yet_open'
    reasons.push(`window opens ${opens} day(s) before the due date`)
  }

  if (!officer) {
    reasons.push('NO ACCOUNTABLE OFFICER: nobody is answerable for this filing')
  }

  return {
    specId: spec.id,
    dueDate: toIsoDate(due),
    // An obligation with no named officer always needs attention, whatever the
    // date says — an unowned filing is how a deadline gets missed with everyone
    // assuming someone else had it.
    status,
    daysUntilDue: days,
    // 'overdue' is deliberately NOT tested here: that case returned early above,
    // already carrying actionRequired: true. Leaving the comparison in place read as
    // though overdue were handled at this point, and strict TS rejected it as an
    // impossible comparison — the union is narrowed to the four non-overdue states.
    actionRequired: status === 'due_soon' || !officer,
    accountableOfficerId: officer?.id ?? null,
    reasons,
  }
}

// ─── §4 Accountability ───────────────────────────────────────────────────────

/**
 * The officer answerable for a filing, or null. Fail-closed: a partially
 * specified officer is NOT an officer. Half a contact record creates the
 * appearance of ownership without the substance, which is worse than an
 * explicit gap because it suppresses the alarm.
 */
export function accountableOfficer(spec: FilingSpec | null | undefined): AccountableOfficer | null {
  const officer = spec?.accountableOfficer
  if (!officer) return null
  const id = `${officer.id ?? ''}`.trim()
  const name = `${officer.name ?? ''}`.trim()
  const role = `${officer.role ?? ''}`.trim()
  const email = `${officer.email ?? ''}`.trim()
  if (!id || !name || !role || !email) return null
  if (!email.includes('@')) return null
  return { id, name, role, email }
}

/** Every filing in `specs` that nobody is answerable for. */
export function unownedFilings(specs: FilingSpec[]): FilingSpec[] {
  return (specs ?? []).filter((spec) => accountableOfficer(spec) === null)
}

// ─── §5 Regulator data feed ──────────────────────────────────────────────────

export interface RegulatorFeedRecord {
  specId: string
  authority: string
  jurisdiction: string
  form: string
  cadence: FilingCadence
  dueDate: string | null
  status: FilingStatus
  daysUntilDue: number | null
  accountableOfficerId: string | null
  actionRequired: boolean
}

/** Normalise an assessed filing into the one shape the regulator feed emits. */
export function regulatorFeedRecord(
  spec: FilingSpec,
  now: Date | string,
  filedFor?: Date | string | null,
): RegulatorFeedRecord {
  const assessment = assessFiling(spec, now, filedFor)
  return {
    specId: assessment.specId,
    authority: spec?.authority ?? '',
    jurisdiction: spec?.jurisdiction ?? '',
    form: spec?.form ?? '',
    cadence: spec?.cadence ?? 'event_driven',
    dueDate: assessment.dueDate,
    status: assessment.status,
    daysUntilDue: assessment.daysUntilDue,
    accountableOfficerId: assessment.accountableOfficerId,
    actionRequired: assessment.actionRequired,
  }
}

/** Feed records ordered so the most urgent obligation is always first. */
export function regulatorFeed(
  specs: FilingSpec[],
  now: Date | string,
): RegulatorFeedRecord[] {
  const rank: Record<FilingStatus, number> = {
    overdue: 0,
    unknown: 1,
    due_soon: 2,
    open: 3,
    not_yet_open: 4,
    filed: 5,
  }
  return (specs ?? [])
    .map((spec) => regulatorFeedRecord(spec, now))
    .sort((a, b) => {
      const byStatus = rank[a.status] - rank[b.status]
      if (byStatus !== 0) return byStatus
      const aDays = a.daysUntilDue ?? Number.MAX_SAFE_INTEGER
      const bDays = b.daysUntilDue ?? Number.MAX_SAFE_INTEGER
      return aDays - bDays
    })
}
