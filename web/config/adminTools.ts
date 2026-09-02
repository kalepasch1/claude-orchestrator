export interface AdminTool {
  label: string
  to: string
  icon: string
  blurb: string
  group: 'Operate' | 'Observe' | 'Govern' | 'Money'
}

/**
 * The admin section's own index.
 *
 * There are 23 screens under pages/admin/. Before this file, the sidebar's one
 * admin link pointed at a single leaf (/admin/capability-passport) and
 * /admin/index.vue listed only the per-app cards — so 22 of those screens had no
 * inbound link anywhere in the application. They were reachable only by typing
 * the URL, which in practice means they were reachable by whoever wrote them,
 * once.
 *
 * Two of them are the development terminals. The operator's stated reason for
 * opening this app is to steer the fleet from a terminal, and the terminal was
 * the least discoverable thing in it.
 *
 * Kept as data, next to CANONICAL_NAVIGATION and for the same reason: a screen
 * that exists but cannot be found is indistinguishable from a screen that was
 * never built, and a list in a config file can be checked against the
 * filesystem. scripts/verify-admin-index.mjs does exactly that.
 */
export const ADMIN_TOOLS: readonly AdminTool[] = Object.freeze([
  // ── Operate ────────────────────────────────────────────────────────────
  { label: 'Development terminal', to: '/admin/terminal', icon: '▮', group: 'Operate',
    blurb: 'Run commands, read and edit files, and query the control plane in one session.' },
  { label: 'Playbooks', to: '/admin/playbooks', icon: '▤', group: 'Operate',
    blurb: 'The standing procedures the fleet runs, and what each one last decided.' },
  { label: 'Prompt ops', to: '/admin/prompt-ops', icon: '✎', group: 'Operate',
    blurb: 'Prompt versions in play, and how each is performing against the last.' },
  { label: 'Chat', to: '/admin/chat', icon: '◗', group: 'Operate',
    blurb: 'Direct conversation with the orchestrator over the current fleet state.' },
  { label: 'Deploys', to: '/admin/deploys', icon: '▲', group: 'Operate',
    blurb: 'What shipped, when, and which commit each release actually contains.' },
  { label: 'Gateway', to: '/admin/gateway', icon: '⇄', group: 'Operate',
    blurb: 'Inbound and outbound routing across the portfolio.' },

  // ── Observe ────────────────────────────────────────────────────────────
  { label: 'Telemetry', to: '/admin/telemetry', icon: '∿', group: 'Observe',
    blurb: 'Live signal from the runners: throughput, latency, and where time goes.' },
  { label: 'Anomalies', to: '/admin/anomalies', icon: '⚠', group: 'Observe',
    blurb: 'Deviations the fleet flagged but no one has closed out.' },
  { label: 'Events', to: '/admin/events', icon: '◦', group: 'Observe',
    blurb: 'The raw event stream, unaggregated, for when a summary is not enough.' },
  { label: 'Session replay', to: '/admin/session-replay', icon: '↺', group: 'Observe',
    blurb: 'Step back through a run exactly as it happened.' },
  { label: 'Replay', to: '/admin/replay', icon: '⟲', group: 'Observe',
    blurb: 'Re-run a past decision against current code to see what would differ.' },
  { label: 'Shadow', to: '/admin/shadow', icon: '◑', group: 'Observe',
    blurb: 'Changes running in shadow, compared against the live path.' },
  { label: 'Predictions', to: '/admin/predictions', icon: '◔', group: 'Observe',
    blurb: 'What the fleet expected to happen, scored against what did.' },
  { label: 'Knowledge graph', to: '/admin/knowledge-graph', icon: '⬡', group: 'Observe',
    blurb: 'How entities across the portfolio actually relate.' },
  { label: 'Temporal', to: '/admin/temporal', icon: '◷', group: 'Observe',
    blurb: 'The same system viewed across time rather than at an instant.' },

  // ── Govern ─────────────────────────────────────────────────────────────
  { label: 'Capability passport', to: '/admin/capability-passport', icon: '⚙', group: 'Govern',
    blurb: 'What each capability is permitted to do, and the routing that enforces it.' },
  { label: 'Policies', to: '/admin/policies', icon: '§', group: 'Govern',
    blurb: 'Standing rules the fleet must satisfy before it may act.' },
  { label: 'Compliance', to: '/admin/compliance', icon: '✓', group: 'Govern',
    blurb: 'Continuous control status, and which evidence is missing.' },
  { label: 'Regulatory', to: '/admin/regulatory', icon: '⚖', group: 'Govern',
    blurb: 'Jurisdictional posture and the authority behind each position.' },
  { label: 'Users', to: '/admin/users', icon: '☺', group: 'Govern',
    blurb: 'Who has access, at what level, and how it was granted.' },
  { label: 'Chaos', to: '/admin/chaos', icon: '✷', group: 'Govern',
    blurb: 'Deliberate failure injection, and what survived it.' },

  // ── Money ──────────────────────────────────────────────────────────────
  { label: 'Costs', to: '/admin/costs', icon: '−', group: 'Money',
    blurb: 'What the fleet spent, split by provider and by project.' },
  { label: 'Revenue', to: '/admin/revenue', icon: '+', group: 'Money',
    blurb: 'What the portfolio earned, against what it cost to earn it.' },
])

export const ADMIN_GROUPS = ['Operate', 'Observe', 'Govern', 'Money'] as const
