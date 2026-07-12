/**
 * Compliance Graph — maps cross-app dependencies for regulatory actions.
 * When a compliance event fires in one app, the graph traces the impact
 * across the fleet and suggests/executes cascading responses.
 */

import { ALL_APP_IDS, type AppId } from './appClients'

export interface ComplianceNode {
  app: string
  entity: string  // 'user' | 'transaction' | 'document' | 'feature'
  entityId?: string
  status: 'clean' | 'flagged' | 'suspended' | 'blocked'
}

export interface ComplianceEdge {
  source: { app: string; entity: string }
  target: { app: string; entity: string }
  relationship: 'owns' | 'references' | 'depends_on' | 'mirrors'
  propagation: 'auto' | 'manual'
}

export interface ImpactAnalysis {
  triggerApp: string
  triggerAction: string
  affectedNodes: ComplianceNode[]
  suggestedActions: { app: string; action: string; reason: string; auto: boolean }[]
  timestamp: string
}

// Default edges — hardcoded knowledge of cross-app relationships
const edges: ComplianceEdge[] = [
  // User identity flows
  { source: { app: 'apparently', entity: 'user' }, target: { app: 'smarter', entity: 'user' }, relationship: 'mirrors', propagation: 'auto' },
  { source: { app: 'apparently', entity: 'user' }, target: { app: 'tomorrow', entity: 'user' }, relationship: 'mirrors', propagation: 'auto' },
  { source: { app: 'apparently', entity: 'user' }, target: { app: 'galop', entity: 'user' }, relationship: 'mirrors', propagation: 'auto' },
  { source: { app: 'apparently', entity: 'user' }, target: { app: 'hisanta', entity: 'user' }, relationship: 'mirrors', propagation: 'auto' },
  // Compliance state flows
  { source: { app: 'apparently', entity: 'document' }, target: { app: 'tomorrow', entity: 'transaction' }, relationship: 'depends_on', propagation: 'manual' },
  { source: { app: 'apparently', entity: 'document' }, target: { app: 'smarter', entity: 'document' }, relationship: 'mirrors', propagation: 'auto' },
  { source: { app: 'galop', entity: 'user' }, target: { app: 'hisanta', entity: 'user' }, relationship: 'references', propagation: 'auto' },
  { source: { app: 'tomorrow', entity: 'transaction' }, target: { app: 'pareto', entity: 'feature' }, relationship: 'depends_on', propagation: 'manual' },
  { source: { app: 'smarter', entity: 'user' }, target: { app: 'orchestrator', entity: 'user' }, relationship: 'references', propagation: 'auto' },
  { source: { app: 'pareto', entity: 'user' }, target: { app: 'galop', entity: 'user' }, relationship: 'mirrors', propagation: 'auto' },
]

// In-memory node registry (populated from edges + impact analyses)
const nodeRegistry: Map<string, ComplianceNode> = new Map()

// Initialize nodes from edges
function ensureNodesFromEdges(): void {
  for (const edge of edges) {
    const sourceKey = `${edge.source.app}:${edge.source.entity}`
    const targetKey = `${edge.target.app}:${edge.target.entity}`
    if (!nodeRegistry.has(sourceKey)) {
      nodeRegistry.set(sourceKey, { app: edge.source.app, entity: edge.source.entity, status: 'clean' })
    }
    if (!nodeRegistry.has(targetKey)) {
      nodeRegistry.set(targetKey, { app: edge.target.app, entity: edge.target.entity, status: 'clean' })
    }
  }
}

// Ensure initialization
ensureNodesFromEdges()

// Impact analysis history
const impactHistory: ImpactAnalysis[] = []

// Compliance action mappings
const ACTION_MAP: Record<string, { action: string; reason: string }> = {
  'user:flagged': { action: 'flag_user', reason: 'User flagged in source app — mirror flag across fleet' },
  'user:suspended': { action: 'suspend_user', reason: 'User suspended — propagate suspension to dependent apps' },
  'user:blocked': { action: 'block_user', reason: 'User blocked — enforce block across all mirrored apps' },
  'document:flagged': { action: 'review_document', reason: 'Document flagged — review dependent transactions and mirrors' },
  'document:suspended': { action: 'freeze_document', reason: 'Document suspended — freeze downstream transactions' },
  'transaction:flagged': { action: 'hold_transaction', reason: 'Transaction flagged — hold and review dependent features' },
  'transaction:suspended': { action: 'freeze_transaction', reason: 'Transaction suspended — block dependent features' },
  'feature:flagged': { action: 'disable_feature', reason: 'Feature flagged — evaluate impact on users' },
  'feature:blocked': { action: 'kill_feature', reason: 'Feature blocked — disable across fleet' },
}

/**
 * Trace all nodes reachable from a given app+entity via edges (BFS).
 */
export function traceEntity(app: string, entityType: string, entityId?: string): ComplianceNode[] {
  const startKey = `${app}:${entityType}`
  const visited = new Set<string>([startKey])
  const queue = [startKey]
  const result: ComplianceNode[] = []

  while (queue.length > 0) {
    const current = queue.shift()!
    const [currentApp, currentEntity] = current.split(':')

    for (const edge of edges) {
      const edgeSourceKey = `${edge.source.app}:${edge.source.entity}`
      const edgeTargetKey = `${edge.target.app}:${edge.target.entity}`

      if (edgeSourceKey === current && !visited.has(edgeTargetKey)) {
        visited.add(edgeTargetKey)
        queue.push(edgeTargetKey)
        const node = nodeRegistry.get(edgeTargetKey) || { app: edge.target.app, entity: edge.target.entity, status: 'clean' as const }
        result.push({ ...node, entityId })
      }
    }
  }

  return result
}

/**
 * Analyze the impact of a compliance action on a given app/entity.
 */
export function analyzeImpact(triggerApp: string, triggerAction: string, entityType: string, entityId?: string): ImpactAnalysis {
  const affectedNodes = traceEntity(triggerApp, entityType, entityId)

  // Generate suggested actions based on the trigger and relationships
  const suggestedActions: { app: string; action: string; reason: string; auto: boolean }[] = []

  for (const node of affectedNodes) {
    const actionKey = `${node.entity}:${triggerAction}`
    const mapping = ACTION_MAP[actionKey] || { action: `review_${node.entity}`, reason: `Cascading review needed due to ${triggerAction} in ${triggerApp}` }

    // Find the edge to determine if propagation is auto
    const edge = edges.find(e =>
      e.target.app === node.app && e.target.entity === node.entity
    )

    suggestedActions.push({
      app: node.app,
      action: mapping.action,
      reason: mapping.reason,
      auto: edge?.propagation === 'auto',
    })
  }

  const analysis: ImpactAnalysis = {
    triggerApp,
    triggerAction,
    affectedNodes,
    suggestedActions,
    timestamp: new Date().toISOString(),
  }

  // Store in history
  impactHistory.unshift(analysis)
  if (impactHistory.length > 50) impactHistory.pop()

  return analysis
}

/**
 * Return the full compliance graph.
 */
export function getGraph(): { nodes: ComplianceNode[]; edges: ComplianceEdge[] } {
  ensureNodesFromEdges()
  return {
    nodes: Array.from(nodeRegistry.values()),
    edges: [...edges],
  }
}

/**
 * Add a new edge to the graph.
 */
export function addEdge(edge: ComplianceEdge): void {
  edges.push(edge)
  ensureNodesFromEdges()
}

/**
 * Get impact analysis history.
 */
export function getImpactHistory(): ImpactAnalysis[] {
  return impactHistory
}
