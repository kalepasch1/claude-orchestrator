/**
 * realtimeMonitor.ts — Real-time monitoring stub for approval workflows.
 */
export interface MonitorEvent {
  eventType: 'approval_requested' | 'approval_granted' | 'approval_denied' | 'timeout'
  taskId: string
  timestamp: number
}

export function createEvent(eventType: MonitorEvent['eventType'], taskId: string, nowMs?: number): MonitorEvent {
  return { eventType, taskId, timestamp: nowMs ?? Date.now() }
}
