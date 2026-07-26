import { ref, onMounted, onUnmounted } from 'vue'

// useFleetWebSocket — subscribes to Supabase Realtime channels for live task updates.
// Replaces the raw WebSocket approach from the original spec, using the
// existing @nuxtjs/supabase module already wired in nuxt.config.ts.

type TopicHandler = (payload: any) => void

export interface FleetEvent {
  topic: string
  payload: any
  timestamp: string
}

export function useFleetWebSocket() {
  const events = ref<FleetEvent[]>([])
  const connected = ref(false)
  const handlers = new Map<string, TopicHandler[]>()
  let channel: ReturnType<ReturnType<typeof useSupabaseClient>['channel']> | null = null

  function on(topic: string, handler: TopicHandler) {
    if (!handlers.has(topic)) handlers.set(topic, [])
    handlers.get(topic)!.push(handler)
  }

  function off(topic: string, handler: TopicHandler) {
    const list = handlers.get(topic)
    if (list) {
      const idx = list.indexOf(handler)
      if (idx !== -1) list.splice(idx, 1)
    }
  }

  function emit(topic: string, payload: any) {
    const event: FleetEvent = { topic, payload, timestamp: new Date().toISOString() }
    events.value = [event, ...events.value.slice(0, 99)]
    const list = handlers.get(topic) ?? []
    for (const h of list) h(payload)
    // wildcard
    const wild = handlers.get('*') ?? []
    for (const h of wild) h({ topic, ...payload })
  }

  const supabase = useSupabaseClient<any>()

  onMounted(() => {
    channel = supabase
      .channel('fleet-realtime')
      .on('postgres_changes', { event: '*', schema: 'public', table: 'tasks' }, (payload: any) => {
        const state: string = payload.new?.state ?? payload.old?.state ?? 'unknown'
        emit('task:update', { task: payload.new ?? payload.old, event_type: payload.eventType, state })

        if (['DONE', 'MERGED'].includes(state)) emit('task:complete', payload.new)
        if (['BLOCKED', 'TESTFAIL', 'BUILDFAIL'].includes(state)) emit('task:blocked', payload.new)
        if (state === 'RUNNING') emit('task:running', payload.new)
        if ((payload.new?.cascade_confidence ?? null) !== null) emit('cascade:update', { confidence: payload.new.cascade_confidence, model_tier: payload.new.model_tier, slug: payload.new.slug })
      })
      .subscribe((status: string) => {
        connected.value = status === 'SUBSCRIBED'
      })
  })

  onUnmounted(() => {
    if (channel) supabase.removeChannel(channel)
  })

  return { connected, events, on, off }
}
