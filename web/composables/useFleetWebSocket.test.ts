import { describe, it, expect } from 'vitest'
import {
  mapTaskChangeToEvents,
  toTaskUpdateMessage,
  TASK_UPDATE_TYPE,
} from './useFleetWebSocket'

// Simulates the payloads Supabase Realtime hands the subscribe callback for
// `postgres_changes` on public.tasks.
function change(newRow: any, oldRow: any = null, eventType = 'UPDATE') {
  return { new: newRow, old: oldRow, eventType }
}

function topics(payload: any) {
  return mapTaskChangeToEvents(payload).map((e) => e.topic)
}

function payloadFor(events: Array<{ topic: string; payload: any }>, topic: string) {
  return events.find((e) => e.topic === topic)?.payload
}

describe('toTaskUpdateMessage', () => {
  it('builds the documented wire schema', () => {
    const msg = toTaskUpdateMessage(
      { id: 't-1', slug: 'fix-thing', progress: 42 },
      'RUNNING',
    )
    expect(msg).toEqual({
      type: 'task-update',
      taskId: 't-1',
      slug: 'fix-thing',
      status: 'RUNNING',
      progress: 42,
    })
    expect(msg.type).toBe(TASK_UPDATE_TYPE)
  })

  it('keeps progress null when absent rather than reporting 0%', () => {
    const msg = toTaskUpdateMessage({ id: 't-2', slug: 's' }, 'QUEUED')
    expect(msg.progress).toBeNull()
  })

  it('reports 0 progress as 0, not null', () => {
    const msg = toTaskUpdateMessage({ id: 't-3', slug: 's', progress: 0 }, 'RUNNING')
    expect(msg.progress).toBe(0)
  })

  it('survives a missing row', () => {
    const msg = toTaskUpdateMessage(undefined, 'unknown')
    expect(msg).toEqual({
      type: 'task-update',
      taskId: null,
      slug: null,
      status: 'unknown',
      progress: null,
    })
  })
})

describe('mapTaskChangeToEvents', () => {
  it('always emits task:update carrying the row, event type and message', () => {
    const row = { id: 't-1', slug: 'a', state: 'RUNNING', progress: 10 }
    const events = mapTaskChangeToEvents(change(row, null, 'UPDATE'))
    const update = payloadFor(events, 'task:update')

    expect(update.task).toEqual(row)
    expect(update.event_type).toBe('UPDATE')
    expect(update.state).toBe('RUNNING')
    expect(update.message).toEqual({
      type: 'task-update',
      taskId: 't-1',
      slug: 'a',
      status: 'RUNNING',
      progress: 10,
    })
  })

  it('emits task:running alongside task:update for a started task', () => {
    expect(topics(change({ id: 't', state: 'RUNNING' }))).toEqual([
      'task:update',
      'task:running',
    ])
  })

  it.each(['DONE', 'MERGED'])('emits task:complete for %s', (state) => {
    const events = topics(change({ id: 't', state }))
    expect(events).toContain('task:complete')
    expect(events).not.toContain('task:blocked')
  })

  it.each(['BLOCKED', 'TESTFAIL', 'BUILDFAIL'])('emits task:blocked for %s', (state) => {
    const events = topics(change({ id: 't', state }))
    expect(events).toContain('task:blocked')
    expect(events).not.toContain('task:complete')
  })

  it('does not emit a terminal topic for an in-between state', () => {
    expect(topics(change({ id: 't', state: 'QUEUED' }))).toEqual(['task:update'])
  })

  it('emits cascade:update only when cascade_confidence is present', () => {
    const withCascade = change({
      id: 't',
      slug: 'a',
      state: 'RUNNING',
      cascade_confidence: 0.8,
      model_tier: 'sonnet',
    })
    expect(payloadFor(mapTaskChangeToEvents(withCascade), 'cascade:update')).toEqual({
      confidence: 0.8,
      model_tier: 'sonnet',
      slug: 'a',
    })

    expect(topics(change({ id: 't', state: 'RUNNING' }))).not.toContain('cascade:update')
  })

  it('treats cascade_confidence 0 as present, not missing', () => {
    const events = topics(
      change({ id: 't', slug: 'a', state: 'RUNNING', cascade_confidence: 0 }),
    )
    expect(events).toContain('cascade:update')
  })

  it('falls back to the old row on DELETE', () => {
    const old = { id: 't-9', slug: 'gone', state: 'DONE' }
    const events = mapTaskChangeToEvents(change(null, old, 'DELETE'))
    const update = payloadFor(events, 'task:update')

    expect(update.task).toEqual(old)
    expect(update.state).toBe('DONE')
    // task:complete carries payload.new, which is null on a delete.
    expect(payloadFor(events, 'task:complete')).toBeNull()
  })

  it('degrades to "unknown" rather than throwing on a malformed payload', () => {
    const events = mapTaskChangeToEvents({})
    expect(events).toHaveLength(1)
    expect(payloadFor(events, 'task:update').state).toBe('unknown')
    expect(() => mapTaskChangeToEvents(undefined)).not.toThrow()
  })
})

describe('UI reacts to a received task-update message', () => {
  it('updates the task list in place without a refetch', () => {
    // Stand-in for the rendered task list.
    const list = [
      { id: 't-1', slug: 'a', state: 'QUEUED', progress: null as number | null },
      { id: 't-2', slug: 'b', state: 'RUNNING', progress: 20 as number | null },
    ]

    // The handler a component registers via `on('task:update', ...)`.
    function onTaskUpdate(payload: any) {
      const msg = payload.message
      const row = list.find((t) => t.id === msg.taskId)
      if (row) {
        row.state = msg.status
        if (msg.progress !== null) row.progress = msg.progress
      }
    }

    for (const e of mapTaskChangeToEvents(
      change({ id: 't-1', slug: 'a', state: 'RUNNING', progress: 55 }),
    )) {
      if (e.topic === 'task:update') onTaskUpdate(e.payload)
    }

    expect(list[0]).toEqual({ id: 't-1', slug: 'a', state: 'RUNNING', progress: 55 })
    // The unrelated row is untouched.
    expect(list[1]).toEqual({ id: 't-2', slug: 'b', state: 'RUNNING', progress: 20 })
  })
})
