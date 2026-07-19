export interface NavigationItem { label: string; icon: string; to: string; aliases?: string[] }

/**
 * Public UX contract. Order, labels, and canonical destinations are intentionally stable.
 * Adaptive guidance may recommend these destinations but must never mutate this array.
 */
export const CANONICAL_NAVIGATION: readonly NavigationItem[] = Object.freeze([
  { label: 'Command Center', icon: '→', to: '/', aliases: ['/index'] },
  { label: 'Sign-offs', icon: '○', to: '/sign-offs' },
  { label: 'Queue', icon: '≡', to: '/queue' },
  { label: 'Orchestrators', icon: '◈', to: '/orchestrators' },
  { label: 'Connections', icon: '↔', to: '/connectors', aliases: ['/connections', '/integrations'] },
  { label: 'Digital Twin', icon: '◐', to: '/digital-twin', aliases: ['/simulation'] },
  { label: 'Spend & ROI', icon: '$', to: '/spend' },
  { label: 'Loops', icon: '∞', to: '/loops' },
  { label: 'Inbox', icon: '⊡', to: '/inbox' },
  { label: 'Fleet', icon: '◉', to: '/fleet' },
  { label: 'Health', icon: '♡', to: '/health' },
])

export const NAVIGATION_CONTRACT_VERSION = 1
