export interface RegFactArrival {
  timestamp: Date
  domain: string
  jurisdiction: string
  fact_type: string
}

export interface VelocityResult {
  velocity_score: number
  acceleration_rate: number
  is_accelerating: boolean
  fact_count: number
  arrival_interval_hours: number
  computed_at: string
  window_start: string
  window_end: string
}

export interface CadenceUpdate {
  source_id: string
  domain: string
  jurisdiction: string
  previous_cadence_hours: number
  new_cadence_hours: number
  alert_urgency: string
  alert_reason: string
  velocity_snapshot: VelocityResult
  updated_at: string
}

const CADENCE_FLOOR_HOURS = 6
const VELOCITY_SCORE_CAP = 100

export function computeVelocity(
  arrivals: RegFactArrival[],
  domain?: string,
  jurisdiction?: string
): VelocityResult {
  const now = new Date()

  // Filter by domain and jurisdiction if specified
  let filtered = arrivals
  if (domain || jurisdiction) {
    filtered = arrivals.filter((a) => {
      if (domain && a.domain !== domain) return false
      if (jurisdiction && a.jurisdiction !== jurisdiction) return false
      return true
    })
  }

  // Filter out invalid timestamps and sort chronologically
  const validArrivals = filtered
    .filter((a) => a && a.timestamp instanceof Date && !isNaN(a.timestamp.getTime()))
    .sort((a, b) => a.timestamp.getTime() - b.timestamp.getTime())

  const result: VelocityResult = {
    velocity_score: 0,
    acceleration_rate: 0,
    is_accelerating: false,
    fact_count: validArrivals.length,
    arrival_interval_hours: 0,
    computed_at: now.toISOString(),
    window_start: validArrivals.length > 0 ? validArrivals[0].timestamp.toISOString() : now.toISOString(),
    window_end: now.toISOString(),
  }

  // Need at least 2 facts to compute velocity
  if (validArrivals.length < 2) {
    return result
  }

  // Calculate intervals between consecutive arrivals (in hours)
  const intervals: number[] = []
  for (let i = 1; i < validArrivals.length; i++) {
    const prev = validArrivals[i - 1].timestamp.getTime()
    const curr = validArrivals[i].timestamp.getTime()
    const intervalHours = (curr - prev) / (1000 * 60 * 60)
    intervals.push(intervalHours)
  }

  // Calculate average interval
  const avgInterval = intervals.reduce((a, b) => a + b, 0) / intervals.length
  result.arrival_interval_hours = avgInterval

  // Compute velocity score: normalized by 1/average_interval (faster arrivals = higher velocity)
  // Scale so that 1-hour average intervals yield high velocity, 24+ hour intervals yield low velocity
  if (avgInterval > 0) {
    // Invert: lower intervals = higher score
    // 1 hour = score ~80, 6 hours = score ~50, 24 hours = score ~15, 48 hours = score ~8
    const velocityBase = Math.max(0, 100 - avgInterval * 3)
    result.velocity_score = Math.min(VELOCITY_SCORE_CAP, velocityBase)
  }

  // Calculate acceleration: change in interval rate over time
  // Positive acceleration_rate = intervals getting shorter = accelerating
  if (intervals.length >= 2) {
    const recentIntervals = intervals.slice(-Math.ceil(intervals.length / 2))
    const earlyIntervals = intervals.slice(0, Math.ceil(intervals.length / 2))
    const recentAvg = recentIntervals.reduce((a, b) => a + b, 0) / recentIntervals.length
    const earlyAvg = earlyIntervals.reduce((a, b) => a + b, 0) / earlyIntervals.length

    // Acceleration is change in average interval (positive = shorter intervals = accelerating)
    result.acceleration_rate = (earlyAvg - recentAvg) / Math.max(1, earlyAvg)

    // is_accelerating: true if recent intervals are shorter than early intervals
    result.is_accelerating = recentAvg < earlyAvg
  }

  return result
}

export async function updateHiveSourceCadence(
  sourceId: string,
  domain: string,
  jurisdiction: string,
  velocity: VelocityResult,
  currentCadence: number,
  db: (query: string, params?: any) => Promise<any>,
  ceiling?: number
): Promise<CadenceUpdate> {
  const now = new Date()

  // Calculate new cadence based on velocity
  let newCadence = currentCadence

  // Only lower cadence when accelerating
  if (velocity.is_accelerating) {
    // Scale reduction by velocity magnitude: higher velocity = more aggressive reduction
    const reductionFactor = Math.min(0.9, velocity.velocity_score / 100)
    newCadence = Math.floor(currentCadence * (1 - reductionFactor))

    // Apply ceiling if specified
    if (ceiling !== undefined) {
      newCadence = Math.min(newCadence, ceiling)
    }

    // Apply floor
    newCadence = Math.max(CADENCE_FLOOR_HOURS, newCadence)
  }

  // Never increase cadence, only lower or maintain
  newCadence = Math.min(newCadence, currentCadence)

  // Determine alert urgency and reason
  let alertUrgency = 'normal'
  let alertReason = 'No significant change in regulatory activity'

  if (velocity.is_accelerating) {
    alertUrgency = 'high'
    alertReason = `Regulatory activity accelerating in ${domain}/${jurisdiction} domain; velocity score: ${Math.round(velocity.velocity_score)}, acceleration rate: ${velocity.acceleration_rate.toFixed(2)}`
  }

  // Write update to database
  const query = `
    UPDATE hive_scout_sources
    SET cadence_hours = $1, last_velocity_check = $2, alert_urgency = $3
    WHERE source_id = $4 AND domain = $5 AND jurisdiction = $6
    RETURNING *
  `
  await db(query, [newCadence, now.toISOString(), alertUrgency, sourceId, domain, jurisdiction])

  return {
    source_id: sourceId,
    domain,
    jurisdiction,
    previous_cadence_hours: currentCadence,
    new_cadence_hours: newCadence,
    alert_urgency: alertUrgency,
    alert_reason: alertReason,
    velocity_snapshot: velocity,
    updated_at: now.toISOString(),
  }
}
