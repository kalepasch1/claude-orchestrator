/**
 * Keyboard navigation for the steering workspace, as a pure reducer.
 * `g` then a view key jumps to a rail section and focuses its rail row; `j` / `k` move
 * through the active section's rows; Enter opens the focused row; Escape closes.
 * Typing in a field never navigates.
 */
export interface SteeringView { key: string; id: string; label: string; rows: number }
export interface KeyState { active: string; row: number; pendingG: boolean; focus: 'rail' | 'rows' }
export type KeyEffect = { type: 'none' } | { type: 'go'; id: string } | { type: 'row'; row: number } | { type: 'open'; row: number } | { type: 'close' }

export function isTypingTarget(tag?: string | null, editable?: boolean): boolean {
  return !!editable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(String(tag || '').toUpperCase())
}

export function reduceKey(state: KeyState, key: string, views: SteeringView[], typing = false): { state: KeyState; effect: KeyEffect } {
  const none = { type: 'none' } as const
  if (typing) return { state: { ...state, pendingG: false }, effect: none }
  if (state.pendingG) {
    const view = views.find(v => v.key === key.toLowerCase())
    if (!view) return { state: { ...state, pendingG: false }, effect: none }
    return { state: { active: view.id, row: 0, pendingG: false, focus: 'rail' }, effect: { type: 'go', id: view.id } }
  }
  if (key === 'g') return { state: { ...state, pendingG: true }, effect: none }
  const current = views.find(v => v.id === state.active)
  const count = current?.rows || 0
  if (key === 'j' || key === 'k') {
    if (!count) return { state, effect: none }
    const from = state.focus === 'rows' ? state.row : (key === 'j' ? -1 : count)
    const row = Math.min(count - 1, Math.max(0, from + (key === 'j' ? 1 : -1)))
    return { state: { ...state, row, focus: 'rows' }, effect: { type: 'row', row } }
  }
  if (key === 'Enter' && state.focus === 'rows' && count) return { state, effect: { type: 'open', row: state.row } }
  if (key === 'Escape') return { state: { ...state, focus: 'rail' }, effect: { type: 'close' } }
  return { state, effect: none }
}
