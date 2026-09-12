import { ref, onMounted, onUnmounted } from 'vue'
import {
  buildRequestInitialState,
  createReconnectPolicy,
  isDeadStatus,
  RECONNECT_DEFAULTS,
  REQUEST_INITIAL_STATE,
  type BackoffOptions,
} from './useFleetReconnect'

// useFleetWebSocket — subscribes to Supabase Realtime channels for live task updates.
// Replaces the raw WebSocket approach from the original spec, using the
// existing @nuxtjs/supabase module already wired in nuxt.config.ts.
//
// Transport note: the runner does not push to the client itself. It writes task
// state to Postgres, and Supabase Realtime replicates the row change to every
// subscriber. That is the "server -> client push" — it just runs through the
// database rather than a second socket the Mac runner would have to own.

type TopicHandler = (payload: any) => void

export interface FleetEvent {
  topic: string
  payload: any
  timestamp: string
}

/**
 * Wire format for a task change, kept stable and explicit so both sides of the
 * sync agree on it. Anything consuming `task:update` can rely on `message`.
 */
export interface TaskUpdateMessage {
  type: 'task-update'
  taskId: string | null
  slug: string | null
  status: string
  progress: number | null
}

export const TASK_UPDATE_TYPE = 'task-update' as const

const COMPLETE_STATES = ['DONE', 'MERGED']
const BLOCKED_STATES = ['BLOCKED', 'TESTFAIL', 'BUILDFAIL']

/**
 * Normalise a task row into the task-update wire message.
 *
 * `progress` is optional upstream, so it stays null rather than defaulting to 0
 * — a task with no progress reported is not a task at 0%.
 */
export function toTaskUpdateMessage(row: any, state: string): TaskUpdateMessage {
  const progress = row?.progress
  return {
    type: TASK_UPDATE_TYPE,
    taskId: row?.id ?? null,
    slug: row?.slug ?? null,
    status: state,
    progress: typeof progress === 'number' ? progress : null,
  }
}

/**
 * Pure mapping from a Supabase `postgres_changes` payload to the list of
 * (topic, payload) pairs to emit. Extracted from the subscribe callback so the
 * message contract is testable without mounting a component or a live socket.
 */
export function mapTaskChangeToEvents(payload: any): Array<{ topic: string; payload: any }> {
  const row = payload?.new ?? payload?.old
  const state: string = payload?.new?.state ?? payload?.old?.state ?? 'unknown'
  const out: Array<{ topic: string; payload: any }> = []

  out.push({
    topic: 'task:update',
    payload: {
      task: row,
      event_type: payload?.eventType,
      state,
      message: toTaskUpdateMessage(row, state),
    },
  })

  if (COMPLETE_STATES.includes(state)) out.push({ topic: 'task:complete', payload: payload?.new })
  if (BLOCKED_STATES.includes(state)) out.push({ topic: 'task:blocked', payload: payload?.new })
  if (state === 'RUNNING') out.push({ topic: 'task:running', payload: payload?.new })

  if ((payload?.new?.cascade_confidence ?? null) !== null) {
    out.push({
      topic: 'cascade:update',
      payload: {
        confidence: payload.new.cascade_confidence,
        model_tier: payload.new.model_tier,
        slug: payload.new.slug,
      },
    })
  }

  return out
}

export function useFleetWebSocket(reconnectOptions: BackoffOptions = {}) {
  const events = ref<FleetEvent[]>([])
  const connected = ref(false)
  /** Non-null while waiting out a backoff delay; surfaced so the UI can say so. */
  const reconnectAttempt = ref(0)
  /** True once the attempt budget is spent — the page is now definitively stale. */
  const reconnectExhausted = ref(false)
  /** Timestamp of the newest event actually received, for the catch-up request. */
  const lastEventAt = ref<string | null>(null)
  const handlers = new Map<string, TopicHandler[]>()
  let channel: ReturnType<ReturnType<typeof useSupabaseClient>['channel']> | null = null
  let retryTimer: ReturnType<typeof setTimeout> | null = null
  let disposed = false
  const policy = createReconnectPolicy({ ...RECONNECT_DEFAULTS, ...reconnectOptions })

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
    lastEventAt.value = event.timestamp
    events.value = [event, ...events.value.slice(0, 99)]
    const list = handlers.get(topic) ?? []
    for (const h of list) h(payload)
    // wildcard
    const wild = handlers.get('*') ?? []
    for (const h of wild) h({ topic, ...payload })
  }

  const supabase = useSupabaseClient<any>()

  function teardownChannel() {
    if (!channel) return
    try {
      supabase.removeChannel(channel)
    } catch {
      // Removing an already-dead channel is not an error worth surfacing; the point
      // is to not leak the old subscription before opening a new one.
    }
    channel = null
  }

  function onStatus(status: string) {
    if (disposed) return

    if (status === 'SUBSCRIBED') {
      connected.value = true
      const hadDropped = policy.attempts > 0
      const attempts = policy.attempts
      policy.succeed()
      reconnectAttempt.value = 0
      reconnectExhausted.value = false
      // Re-sync after a reconnect, not on the first connect. Realtime only delivers
      // changes that happen while subscribed, so every row that changed during the
      // gap is invisible: without this the page reconnects and then confidently
      // shows a task list missing exactly the updates the user was waiting for.
      if (hadDropped) {
        emit('sync:request', buildRequestInitialState(lastEventAt.value, attempts))
      }
      return
    }

    if (!isDeadStatus(status)) return

    connected.value = false
    const delay = policy.fail()
    if (delay === null) {
      // Budget spent. Say so loudly rather than retrying forever: a page that is
      // silently not receiving updates looks identical to an idle fleet.
      reconnectExhausted.value = true
      emit('sync:failed', { status, attempts: policy.attempts })
      return
    }
    reconnectAttempt.value = policy.attempts
    emit('sync:reconnecting', { status, attempt: policy.attempts, delayMs: delay })
    scheduleReconnect(delay)
  }

  function scheduleReconnect(delayMs: number) {
    if (retryTimer) clearTimeout(retryTimer)
    retryTimer = setTimeout(() => {
      retryTimer = null
      if (disposed) return
      teardownChannel()
      connect()
    }, delayMs)
  }

  function connect() {
    if (disposed) return
    channel = supabase
      .channel('fleet-realtime')
      .on('postgres_changes', { event: '*', schema: 'public', table: 'tasks' }, (payload: any) => {
        for (const e of mapTaskChangeToEvents(payload)) emit(e.topic, e.payload)
      })
      .subscribe(onStatus)
  }

  function dispose() {
    disposed = true
    if (retryTimer) {
      clearTimeout(retryTimer)
      retryTimer = null
    }
    policy.reset()
    teardownChannel()
  }

  onMounted(connect)
  onUnmounted(dispose)

  return {
    connected,
    events,
    on,
    off,
    reconnectAttempt,
    reconnectExhausted,
    lastEventAt,
    // Exposed for tests and for a manual "retry now" control in the UI.
    _connect: connect,
    _onStatus: onStatus,
    _dispose: dispose,
  }
}

export { REQUEST_INITIAL_STATE }
