export function useExperienceTelemetry(surface: string) {
  const supabase = useSupabaseClient<any>()
  const route = useRoute()
  async function track(event: 'action_started' | 'action_completed' | 'guidance_followed' | 'guidance_dismissed', metadata: Record<string, unknown> = {}) {
    if (!import.meta.client) return
    try {
      const { data: { session } } = await supabase.auth.getSession()
      const headers = session?.access_token ? { authorization: `Bearer ${session.access_token}` } : {}
      await Promise.allSettled([
        $fetch('/api/adaptive/event', { method: 'POST', headers, body: { event, route: route.path, objective: surface, metadata: { surface, ...metadata } } }),
        $fetch('/api/product-metric', { method: 'POST', headers, body: { experiment: 'orchestrator_experience_v2', metric: `${surface}:${event}`, subject: route.path, route: route.path, value: Number(metadata.dwell_ms || 1), guardrail: event === 'guidance_dismissed' } }),
      ])
    } catch {}
  }
  return { track }
}
