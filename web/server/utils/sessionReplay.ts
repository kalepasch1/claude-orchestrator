/**
 * Cross-App Session Replay — traces user activity across the fleet.
 * Given an email or userId, queries all apps for events involving that user
 * and builds a unified chronological timeline.
 */
import { getAppClient, ALL_APP_IDS, type AppId } from './appClients'
import { serviceClient } from './fleetSupabase'

export interface SessionEvent {
  app: string
  timestamp: string
  type: 'login' | 'action' | 'error' | 'fleet_event' | 'approval'
  description: string
  details?: any
  severity: 'info' | 'warning' | 'critical'
}

export interface UserSession {
  email: string
  userId?: string
  apps: string[]
  timeline: SessionEvent[]
  firstSeen: string
  lastSeen: string
  totalEvents: number
}

interface UserPresence {
  app: string
  userId?: string
  email: string
}

/**
 * Trace a user's activity across all fleet apps.
 * 1. Searches each app for the user by email
 * 2. Queries fleet_admin_events for events mentioning that user
 * 3. Queries fleet_approvals for approval events by that user
 * 4. Merges into a unified timeline
 */
export async function traceUser(email: string): Promise<UserSession> {
  const presence: UserPresence[] = []
  const events: SessionEvent[] = []

  // 1. Search for user in each app's users/profiles table
  const appSearches = ALL_APP_IDS.map(async (appId) => {
    const client = getAppClient(appId)
    if (!client) return

    try {
      // Try common user table names
      for (const table of ['users', 'profiles', 'auth_users']) {
        const { data } = await client
          .from(table)
          .select('id, email, created_at, last_sign_in_at')
          .eq('email', email)
          .limit(1)
          .maybeSingle()

        if (data) {
          presence.push({ app: appId, userId: data.id, email })

          // Add login/signup events if we have timestamps
          if (data.created_at) {
            events.push({
              app: appId,
              timestamp: data.created_at,
              type: 'login',
              description: `Account created in ${appId}`,
              severity: 'info',
            })
          }
          if (data.last_sign_in_at) {
            events.push({
              app: appId,
              timestamp: data.last_sign_in_at,
              type: 'login',
              description: `Last sign-in to ${appId}`,
              severity: 'info',
            })
          }
          break // Found user in this app, no need to check other tables
        }
      }
    } catch {
      // Table doesn't exist in this app — skip silently
    }
  })

  await Promise.allSettled(appSearches)

  // 2. Query fleet_admin_events for events mentioning this user
  const sb = serviceClient()
  try {
    const { data: fleetEvents } = await sb
      .from('fleet_admin_events')
      .select('*')
      .or(`subject_id.eq.${email},details->>email.eq.${email},details->>actor.eq.${email}`)
      .order('at', { ascending: false })
      .limit(500)

    if (fleetEvents) {
      for (const e of fleetEvents) {
        events.push({
          app: e.product || 'orchestrator',
          timestamp: e.at || e.created_at,
          type: 'fleet_event',
          description: e.title || e.summary || `${e.category} event`,
          details: e.details,
          severity: e.severity === 'critical' ? 'critical' : e.severity === 'high' ? 'warning' : 'info',
        })
      }
    }
  } catch {
    // fleet_admin_events might not exist yet
  }

  // 3. Query fleet_approvals for approvals by this user
  try {
    const { data: approvals } = await sb
      .from('fleet_approvals')
      .select('*')
      .eq('approver', email)
      .order('decided_at', { ascending: false })
      .limit(200)

    if (approvals) {
      for (const a of approvals) {
        events.push({
          app: a.product || 'orchestrator',
          timestamp: a.decided_at || a.created_at,
          type: 'approval',
          description: `${a.status}: ${a.title}`,
          details: { tier: a.tier, domain: a.domain, note: a.note },
          severity: a.status === 'rejected' ? 'warning' : 'info',
        })
      }
    }
  } catch {
    // fleet_approvals might not exist yet
  }

  // 4. Query each app's audit_log table if present
  const auditSearches = presence.map(async (p) => {
    const client = getAppClient(p.app as AppId)
    if (!client) return

    try {
      const { data: auditRows } = await client
        .from('audit_log')
        .select('action, created_at, details, severity')
        .eq('user_id', p.userId || '')
        .order('created_at', { ascending: false })
        .limit(100)

      if (auditRows) {
        for (const row of auditRows) {
          events.push({
            app: p.app,
            timestamp: row.created_at,
            type: 'action',
            description: row.action || 'User action',
            details: row.details,
            severity: row.severity || 'info',
          })
        }
      }
    } catch {
      // audit_log doesn't exist in this app — skip
    }
  })

  await Promise.allSettled(auditSearches)

  // Sort timeline chronologically
  events.sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime())

  const apps = [...new Set(presence.map(p => p.app))]

  return {
    email,
    userId: presence[0]?.userId,
    apps,
    timeline: events,
    firstSeen: events[0]?.timestamp || '',
    lastSeen: events[events.length - 1]?.timestamp || '',
    totalEvents: events.length,
  }
}

/**
 * Get summaries of recently active users across the fleet.
 */
export async function getRecentSessions(limit: number = 20): Promise<{
  email: string
  lastSeen: string
  app: string
  eventType: string
  description: string
}[]> {
  const sb = serviceClient()
  const results: { email: string; lastSeen: string; app: string; eventType: string; description: string }[] = []

  try {
    // Pull recent events that have user identifiers
    const { data: recentEvents } = await sb
      .from('fleet_admin_events')
      .select('product, subject_id, title, category, at, details')
      .order('at', { ascending: false })
      .limit(200)

    if (recentEvents) {
      const seen = new Set<string>()
      for (const e of recentEvents) {
        const email = e.subject_id || e.details?.email || e.details?.actor
        if (!email || typeof email !== 'string' || !email.includes('@')) continue
        if (seen.has(email)) continue
        seen.add(email)
        results.push({
          email,
          lastSeen: e.at,
          app: e.product || 'orchestrator',
          eventType: e.category || 'event',
          description: e.title || 'Fleet event',
        })
        if (results.length >= limit) break
      }
    }
  } catch {
    // fleet_admin_events might not exist
  }

  // Also check recent approvals
  try {
    const { data: recentApprovals } = await sb
      .from('fleet_approvals')
      .select('approver, product, title, status, decided_at')
      .not('approver', 'is', null)
      .order('decided_at', { ascending: false })
      .limit(50)

    if (recentApprovals) {
      const seen = new Set(results.map(r => r.email))
      for (const a of recentApprovals) {
        if (!a.approver || seen.has(a.approver)) continue
        seen.add(a.approver)
        results.push({
          email: a.approver,
          lastSeen: a.decided_at,
          app: a.product || 'orchestrator',
          eventType: 'approval',
          description: `${a.status}: ${a.title}`,
        })
        if (results.length >= limit) break
      }
    }
  } catch {}

  return results.slice(0, limit)
}

/**
 * Compare activity timelines for multiple users side by side.
 */
export async function compareUsers(emails: string[]): Promise<UserSession[]> {
  const sessions = await Promise.all(emails.map(e => traceUser(e)))
  return sessions
}
