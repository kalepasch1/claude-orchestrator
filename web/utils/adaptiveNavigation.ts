export type OperatorObjective = 'operate' | 'ship' | 'govern' | 'connect' | 'learn'
export type OperatorRole = 'admin' | 'operator' | 'reviewer' | 'engineer' | 'analyst' | 'new_user'

export interface AdaptiveSignals {
  role: OperatorRole
  objective: OperatorObjective
  permissions: string[]
  runnerCount: number
  pendingApprovals: number
  blockedTasks: number
  readyConnectors: number
  learnedRoutes?: Array<{ route: string; visits: number }>
}

export interface NextAction {
  label: string
  to: string
  reason: string
  score: number
  urgent?: boolean
}

const has = (signals: AdaptiveSignals, permission: string) => !signals.permissions.length || signals.permissions.includes('*') || signals.permissions.includes(permission)

/** Recommendations are adaptive; the canonical navigation itself never moves or disappears. */
export function nextBestActions(signals: AdaptiveSignals): NextAction[] {
  const actions: NextAction[] = []
  if (signals.runnerCount === 0) actions.push({ label: 'Check portfolio health', to: '/health', reason: 'No active runner is reporting', score: 120, urgent: true })
  if (signals.pendingApprovals > 0 && has(signals, 'approvals:decide')) actions.push({ label: `Review ${signals.pendingApprovals} sign-off${signals.pendingApprovals === 1 ? '' : 's'}`, to: '/sign-offs', reason: 'Work is waiting for an operator decision', score: 110 + Math.min(20, signals.pendingApprovals), urgent: true })
  if (signals.blockedTasks > 0 && has(signals, 'tasks:manage')) actions.push({ label: `Unblock ${signals.blockedTasks} task${signals.blockedTasks === 1 ? '' : 's'}`, to: '/queue', reason: 'Queue throughput is constrained', score: 100 + Math.min(15, signals.blockedTasks), urgent: true })
  if (signals.readyConnectors === 0 && has(signals, 'connectors:manage')) actions.push({ label: 'Finish connection setup', to: '/connectors', reason: 'No external capability is ready for routing', score: signals.objective === 'connect' ? 105 : 82 })

  const objective: Record<OperatorObjective, NextAction[]> = {
    operate: [{ label: 'Open Command Center', to: '/', reason: 'Portfolio operations overview', score: 72 }, { label: 'Inspect fleet', to: '/fleet', reason: 'Current cross-application state', score: 68 }],
    ship: [{ label: 'Manage delivery queue', to: '/queue', reason: 'Highest-leverage path to shipped work', score: 78 }, { label: 'Open orchestrators', to: '/orchestrators', reason: 'Route and execute capability work', score: 70 }],
    govern: [{ label: 'Simulate a change', to: '/digital-twin', reason: 'Estimate value and blast radius first', score: 78 }, { label: 'Review sign-offs', to: '/sign-offs', reason: 'Govern consequential changes', score: 70 }],
    connect: [{ label: 'Manage connections', to: '/connectors', reason: 'Add models, services, or MCP tools', score: 80 }, { label: 'Inspect capabilities', to: '/orchestrators', reason: 'See what connected services enable', score: 68 }],
    learn: [{ label: 'Start at Command Center', to: '/', reason: 'Step 1 · learn the portfolio overview', score: 90 }, { label: 'Explore Connections', to: '/connectors', reason: 'Step 2 · understand available capabilities', score: 85 }, { label: 'Try the Digital Twin', to: '/digital-twin', reason: 'Step 3 · preview outcomes safely', score: 80 }],
  }
  actions.push(...objective[signals.objective])
  const learned = signals.learnedRoutes?.find(item => item.visits >= 3)
  if (learned) {
    const labels: Record<string, string> = { '/': 'Command Center', '/sign-offs': 'Sign-offs', '/queue': 'Queue', '/orchestrators': 'Orchestrators', '/connectors': 'Connections', '/digital-twin': 'Digital Twin', '/spend': 'Spend & ROI', '/loops': 'Loops', '/inbox': 'Inbox', '/fleet': 'Fleet', '/health': 'Health' }
    if (labels[learned.route]) actions.push({ label: `Return to ${labels[learned.route]}`, to: learned.route, reason: `Learned from ${learned.visits} recent visits; the destination has not moved`, score: 74 })
  }
  if (signals.role === 'reviewer') actions.push({ label: 'Open sign-offs', to: '/sign-offs', reason: 'Matched to your reviewer role', score: 76 })
  if (signals.role === 'analyst') actions.push({ label: 'Review Spend & ROI', to: '/spend', reason: 'Matched to your analyst role', score: 76 })
  if (signals.role === 'engineer') actions.push({ label: 'Open orchestrators', to: '/orchestrators', reason: 'Matched to your engineering role', score: 76 })
  const unique = new Map<string, NextAction>()
  for (const action of actions) if (!unique.has(action.to) || unique.get(action.to)!.score < action.score) unique.set(action.to, action)
  return [...unique.values()].sort((a, b) => b.score - a.score || a.to.localeCompare(b.to)).slice(0, 3)
}
