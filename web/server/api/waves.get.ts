import { serviceClient } from '../utils/fleetSupabase'
import { requireConnectorUser } from '../utils/connectorFabric'

/**
 * Wave-0 review gate (spec item 3): aggregate for the waves/merge timeline page.
 * Per project: pending release approval cards (the staging→prod gate), upcoming
 * waves (queued tasks with one-line descriptions), running work, recent releases,
 * and recent steering history. Auth-gated; madeus.cc stays private.
 */
function firstLine(text: unknown): string {
  const line = String(text || '')
    .split('\n')
    .find((l) => l.trim() && !l.trim().startsWith('#'))
  return (line || '').trim().slice(0, 160)
}

export default defineEventHandler(async (event) => {
  await requireConnectorUser(event)
  const sb = serviceClient()
  const [cards, queued, running, releases, steering, projects] = await Promise.all([
    sb.from('approvals')
      .select('id,project,slug,title,why,value,risk,detail,brief_json,status,created_at,decided_by,decided_at')
      .eq('kind', 'release')
      .order('created_at', { ascending: false })
      .limit(40),
    sb.from('tasks')
      .select('id,slug,state,kind,project_id,prompt,created_at,submitted_by_label')
      .in('state', ['QUEUED', 'RETRY'])
      .order('created_at', { ascending: true })
      .limit(250),
    sb.from('tasks')
      .select('id,slug,state,kind,project_id,created_at,submitted_by_label')
      .eq('state', 'RUNNING')
      .order('created_at', { ascending: true })
      .limit(100),
    sb.from('releases')
      .select('project,version,from_sha,to_sha,n_changes,deploy_status,note,created_at')
      .order('created_at', { ascending: false })
      .limit(25),
    sb.from('steering_events')
      .select('id,project,actor_label,event_type,rationale,created_at')
      .order('created_at', { ascending: false })
      .limit(30),
    sb.from('projects').select('id,name'),
  ])
  for (const r of [cards, queued, running, releases, projects]) {
    if (r.error) throw createError({ statusCode: 500, message: r.error.message })
  }
  const nameById = new Map<string, string>((projects.data || []).map((p: any) => [p.id, p.name]))
  const upcoming: Record<string, any[]> = {}
  for (const t of queued.data || []) {
    const name = nameById.get(t.project_id) || 'unknown'
    ;(upcoming[name] ||= []).push({
      id: t.id, slug: t.slug, state: t.state, kind: t.kind,
      summary: firstLine(t.prompt),
      submitted_by: t.submitted_by_label || null,
      created_at: t.created_at,
    })
  }
  const active: Record<string, any[]> = {}
  for (const t of running.data || []) {
    const name = nameById.get(t.project_id) || 'unknown'
    ;(active[name] ||= []).push({
      id: t.id, slug: t.slug, kind: t.kind,
      submitted_by: t.submitted_by_label || null,
      created_at: t.created_at,
    })
  }
  return {
    ok: true,
    pending_release_cards: (cards.data || []).filter((c: any) => c.status === 'pending'),
    decided_release_cards: (cards.data || []).filter((c: any) => c.status !== 'pending').slice(0, 10),
    upcoming,
    running: active,
    recent_releases: releases.data || [],
    recent_steering: steering.error ? [] : steering.data || [],
    generated_at: new Date().toISOString(),
  }
})
