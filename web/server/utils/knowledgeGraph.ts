/**
 * Fleet Knowledge Graph — semantic entity graph across all apps.
 * Connects users, documents, transactions, features, and compliance items
 * across the fleet. Enables "show me everything related to user X" queries
 * that trace through auth, billing, compliance, and content in one query.
 */
import { getAppClient, ALL_APP_IDS, type AppId } from './appClients'

// ── Types ──────────────────────────────────────────────────────────────
export type EntityType = 'user' | 'document' | 'transaction' | 'feature' | 'policy' | 'incident' | 'approval' | 'workspace'

export interface GraphNode {
  id: string              // unique: `${app}:${type}:${entityId}`
  app: string
  type: EntityType
  entityId: string
  label: string           // human-readable name
  properties: Record<string, any>
  lastUpdated: string
}

export interface GraphEdge {
  id: string              // `${source}->${target}:${relationship}`
  source: string          // node id
  target: string          // node id
  relationship: string    // 'created_by' | 'owns' | 'approved' | 'flagged' | 'references' | 'part_of' | 'triggered' | 'identity'
  weight: number          // 0-1 importance
  metadata?: Record<string, any>
}

export interface GraphQuery {
  startNode?: string      // node id to start traversal from
  entityType?: EntityType
  app?: string
  email?: string          // find all nodes for a user by email
  keyword?: string        // search labels and properties
  maxDepth?: number       // traversal depth (default 3)
  maxNodes?: number       // result limit (default 50)
}

export interface GraphResult {
  nodes: GraphNode[]
  edges: GraphEdge[]
  paths?: { from: string; to: string; via: string[] }[]
  stats: { totalNodes: number; totalEdges: number; appsTraversed: string[] }
}

export interface GraphStats {
  nodeCount: number
  edgeCount: number
  nodesByType: Record<string, number>
  nodesByApp: Record<string, number>
  edgesByRelationship: Record<string, number>
}

// ── Predefined relationship templates ──────────────────────────────────
export const CROSS_APP_RELATIONSHIPS = [
  { pattern: 'user_identity', description: 'Same user across apps linked by email' },
  { pattern: 'onboarding_chain', apps: ['apparently', 'smarter', 'tomorrow'], description: 'Client onboarding flows through compliance -> workspace -> trading' },
  { pattern: 'compliance_cascade', description: 'Compliance action in one app triggers reviews in others' },
  { pattern: 'revenue_flow', description: 'Billing events across apps for same customer' },
]

// ── In-memory graph store ──────────────────────────────────────────────
const nodeStore = new Map<string, GraphNode>()
const edgeStore = new Map<string, GraphEdge>()

function addNode(node: GraphNode): void {
  nodeStore.set(node.id, node)
}

function addEdge(edge: GraphEdge): void {
  edgeStore.set(edge.id, edge)
}

function makeNodeId(app: string, type: EntityType, entityId: string): string {
  return `${app}:${type}:${entityId}`
}

function makeEdgeId(source: string, target: string, relationship: string): string {
  return `${source}->${target}:${relationship}`
}

// ── Graph construction helpers ─────────────────────────────────────────

async function fetchUsersFromApp(appId: AppId, email: string): Promise<GraphNode[]> {
  const client = getAppClient(appId)
  if (!client) return []

  try {
    // Try auth.admin to list users by email
    const { data } = await client.rpc('get_user_by_email', { target_email: email }).maybeSingle()
    if (data) {
      const node: GraphNode = {
        id: makeNodeId(appId, 'user', data.id || email),
        app: appId,
        type: 'user',
        entityId: data.id || email,
        label: data.display_name || data.full_name || email,
        properties: { email, role: data.role, ...data },
        lastUpdated: new Date().toISOString(),
      }
      return [node]
    }
  } catch {
    // RPC not available, try auth admin
  }

  try {
    const { data: authData } = await client.auth.admin.listUsers({ perPage: 100 })
    const users = authData?.users?.filter((u: any) => u.email === email) || []
    return users.map((u: any) => ({
      id: makeNodeId(appId, 'user', u.id),
      app: appId,
      type: 'user' as EntityType,
      entityId: u.id,
      label: u.user_metadata?.full_name || u.user_metadata?.name || email,
      properties: {
        email: u.email,
        created_at: u.created_at,
        last_sign_in: u.last_sign_in_at,
        provider: u.app_metadata?.provider,
        ...u.user_metadata,
      },
      lastUpdated: new Date().toISOString(),
    }))
  } catch {
    return []
  }
}

async function fetchEventsForUser(appId: AppId, email: string): Promise<GraphNode[]> {
  const client = getAppClient(appId)
  if (!client) return []

  const nodes: GraphNode[] = []

  // Try fleet_events table
  for (const table of ['fleet_events', 'fleet_admin_events']) {
    try {
      const { data } = await client
        .from(table)
        .select('*')
        .or(`actor_email.eq.${email},payload->>email.eq.${email}`)
        .order('created_at', { ascending: false })
        .limit(20)

      if (data) {
        for (const event of data) {
          const type = categorizeEventType(event.event_type || event.action)
          const node: GraphNode = {
            id: makeNodeId(appId, type, event.id),
            app: appId,
            type,
            entityId: event.id,
            label: `${event.event_type || event.action}: ${event.summary || event.description || ''}`.slice(0, 100),
            properties: {
              event_type: event.event_type || event.action,
              created_at: event.created_at,
              severity: event.severity,
              status: event.status,
              ...event.payload,
            },
            lastUpdated: event.created_at || new Date().toISOString(),
          }
          nodes.push(node)
        }
      }
    } catch {
      // Table doesn't exist in this app, skip
    }
  }

  return nodes
}

function categorizeEventType(eventType: string): EntityType {
  if (!eventType) return 'incident'
  const lower = eventType.toLowerCase()
  if (lower.includes('transaction') || lower.includes('billing') || lower.includes('payment')) return 'transaction'
  if (lower.includes('document') || lower.includes('upload') || lower.includes('file')) return 'document'
  if (lower.includes('policy') || lower.includes('compliance') || lower.includes('regulation')) return 'policy'
  if (lower.includes('approval') || lower.includes('approve') || lower.includes('review')) return 'approval'
  if (lower.includes('feature') || lower.includes('deploy') || lower.includes('release')) return 'feature'
  if (lower.includes('workspace') || lower.includes('project') || lower.includes('org')) return 'workspace'
  if (lower.includes('incident') || lower.includes('alert') || lower.includes('error')) return 'incident'
  return 'incident'
}

function linkCrossAppIdentities(): void {
  // Group user nodes by email
  const emailMap = new Map<string, GraphNode[]>()
  for (const node of nodeStore.values()) {
    if (node.type === 'user') {
      const email = node.properties.email
      if (email) {
        const list = emailMap.get(email) || []
        list.push(node)
        emailMap.set(email, list)
      }
    }
  }

  // Create identity edges between same-email users across apps
  for (const [, userNodes] of emailMap) {
    if (userNodes.length < 2) continue
    for (let i = 0; i < userNodes.length; i++) {
      for (let j = i + 1; j < userNodes.length; j++) {
        const edgeId = makeEdgeId(userNodes[i].id, userNodes[j].id, 'identity')
        if (!edgeStore.has(edgeId)) {
          addEdge({
            id: edgeId,
            source: userNodes[i].id,
            target: userNodes[j].id,
            relationship: 'identity',
            weight: 1.0,
            metadata: { description: 'Same user across apps' },
          })
        }
      }
    }
  }
}

function linkUserToEvents(userNodeId: string, eventNodes: GraphNode[]): void {
  for (const event of eventNodes) {
    const relationship = event.type === 'approval' ? 'approved'
      : event.type === 'incident' ? 'flagged'
      : event.type === 'transaction' ? 'owns'
      : 'created_by'

    const edgeId = makeEdgeId(userNodeId, event.id, relationship)
    if (!edgeStore.has(edgeId)) {
      addEdge({
        id: edgeId,
        source: userNodeId,
        target: event.id,
        relationship,
        weight: 0.7,
      })
    }
  }
}

// ── Public API ─────────────────────────────────────────────────────────

export async function buildUserSubgraph(email: string): Promise<GraphResult> {
  const allNodes: GraphNode[] = []
  const appsTraversed: string[] = []

  // 1. Search all apps for user nodes
  const userPromises = ALL_APP_IDS.map(async (appId) => {
    const users = await fetchUsersFromApp(appId, email)
    if (users.length > 0) appsTraversed.push(appId)
    return { appId, users }
  })

  const userResults = await Promise.all(userPromises)

  for (const { appId, users } of userResults) {
    for (const user of users) {
      addNode(user)
      allNodes.push(user)

      // 2. Fetch events for each user
      const events = await fetchEventsForUser(appId as AppId, email)
      for (const event of events) {
        addNode(event)
        allNodes.push(event)
      }

      // 3. Link user to their events
      linkUserToEvents(user.id, events)
    }
  }

  // 4. Auto-detect cross-app edges
  linkCrossAppIdentities()

  // Collect relevant edges
  const nodeIds = new Set(allNodes.map(n => n.id))
  const relevantEdges: GraphEdge[] = []
  for (const edge of edgeStore.values()) {
    if (nodeIds.has(edge.source) || nodeIds.has(edge.target)) {
      relevantEdges.push(edge)
      // Include any referenced nodes we might have missed
      if (!nodeIds.has(edge.source) && nodeStore.has(edge.source)) {
        allNodes.push(nodeStore.get(edge.source)!)
        nodeIds.add(edge.source)
      }
      if (!nodeIds.has(edge.target) && nodeStore.has(edge.target)) {
        allNodes.push(nodeStore.get(edge.target)!)
        nodeIds.add(edge.target)
      }
    }
  }

  return {
    nodes: allNodes,
    edges: relevantEdges,
    stats: {
      totalNodes: allNodes.length,
      totalEdges: relevantEdges.length,
      appsTraversed: [...new Set(appsTraversed)],
    },
  }
}

export async function buildEntitySubgraph(
  app: string,
  type: EntityType,
  entityId: string,
  depth: number = 3
): Promise<GraphResult> {
  const startId = makeNodeId(app, type, entityId)

  // Ensure the start node exists
  if (!nodeStore.has(startId)) {
    // Create a placeholder node
    addNode({
      id: startId,
      app,
      type,
      entityId,
      label: `${type}:${entityId}`,
      properties: {},
      lastUpdated: new Date().toISOString(),
    })
  }

  // BFS traversal
  const visited = new Set<string>()
  const queue: { nodeId: string; currentDepth: number }[] = [{ nodeId: startId, currentDepth: 0 }]
  const resultNodes: GraphNode[] = []
  const resultEdges: GraphEdge[] = []

  while (queue.length > 0) {
    const { nodeId, currentDepth } = queue.shift()!
    if (visited.has(nodeId) || currentDepth > depth) continue
    visited.add(nodeId)

    const node = nodeStore.get(nodeId)
    if (node) resultNodes.push(node)

    // Find connected edges
    for (const edge of edgeStore.values()) {
      if (edge.source === nodeId || edge.target === nodeId) {
        resultEdges.push(edge)
        const neighbor = edge.source === nodeId ? edge.target : edge.source
        if (!visited.has(neighbor)) {
          queue.push({ nodeId: neighbor, currentDepth: currentDepth + 1 })
        }
      }
    }
  }

  const appsTraversed = [...new Set(resultNodes.map(n => n.app))]

  return {
    nodes: resultNodes,
    edges: resultEdges,
    stats: {
      totalNodes: resultNodes.length,
      totalEdges: resultEdges.length,
      appsTraversed,
    },
  }
}

export async function searchGraph(query: GraphQuery): Promise<GraphResult> {
  const maxNodes = query.maxNodes || 50
  const maxDepth = query.maxDepth || 3

  // If email is provided, build user subgraph first
  if (query.email) {
    const result = await buildUserSubgraph(query.email)
    return filterResult(result, query, maxNodes)
  }

  // If startNode is provided, do BFS from that node
  if (query.startNode) {
    const parts = query.startNode.split(':')
    if (parts.length >= 3) {
      const result = await buildEntitySubgraph(parts[0], parts[1] as EntityType, parts.slice(2).join(':'), maxDepth)
      return filterResult(result, query, maxNodes)
    }
  }

  // Keyword search across existing graph
  const matchingNodes: GraphNode[] = []
  const keyword = query.keyword?.toLowerCase()

  for (const node of nodeStore.values()) {
    if (matchingNodes.length >= maxNodes) break

    let matches = true

    if (query.entityType && node.type !== query.entityType) matches = false
    if (query.app && node.app !== query.app) matches = false
    if (keyword) {
      const searchText = `${node.label} ${node.entityId} ${JSON.stringify(node.properties)}`.toLowerCase()
      if (!searchText.includes(keyword)) matches = false
    }

    if (matches) matchingNodes.push(node)
  }

  // Collect edges between matching nodes
  const nodeIds = new Set(matchingNodes.map(n => n.id))
  const matchingEdges: GraphEdge[] = []
  for (const edge of edgeStore.values()) {
    if (nodeIds.has(edge.source) && nodeIds.has(edge.target)) {
      matchingEdges.push(edge)
    }
  }

  return {
    nodes: matchingNodes,
    edges: matchingEdges,
    stats: {
      totalNodes: matchingNodes.length,
      totalEdges: matchingEdges.length,
      appsTraversed: [...new Set(matchingNodes.map(n => n.app))],
    },
  }
}

function filterResult(result: GraphResult, query: GraphQuery, maxNodes: number): GraphResult {
  let nodes = result.nodes

  if (query.entityType) nodes = nodes.filter(n => n.type === query.entityType)
  if (query.app) nodes = nodes.filter(n => n.app === query.app)
  if (query.keyword) {
    const kw = query.keyword.toLowerCase()
    nodes = nodes.filter(n =>
      `${n.label} ${n.entityId} ${JSON.stringify(n.properties)}`.toLowerCase().includes(kw)
    )
  }

  nodes = nodes.slice(0, maxNodes)
  const nodeIds = new Set(nodes.map(n => n.id))
  const edges = result.edges.filter(e => nodeIds.has(e.source) || nodeIds.has(e.target))

  return {
    nodes,
    edges,
    stats: {
      totalNodes: nodes.length,
      totalEdges: edges.length,
      appsTraversed: [...new Set(nodes.map(n => n.app))],
    },
  }
}

export function findPaths(fromNodeId: string, toNodeId: string): { from: string; to: string; via: string[] }[] {
  // BFS to find shortest paths
  const paths: { from: string; to: string; via: string[] }[] = []
  const visited = new Set<string>()
  const queue: { nodeId: string; path: string[] }[] = [{ nodeId: fromNodeId, path: [fromNodeId] }]
  const maxPaths = 5
  const maxSearchDepth = 6

  while (queue.length > 0 && paths.length < maxPaths) {
    const { nodeId, path } = queue.shift()!

    if (path.length > maxSearchDepth) continue

    if (nodeId === toNodeId && path.length > 1) {
      paths.push({ from: fromNodeId, to: toNodeId, via: path.slice(1, -1) })
      continue
    }

    if (visited.has(nodeId) && nodeId !== fromNodeId) continue
    visited.add(nodeId)

    // Find neighbors
    for (const edge of edgeStore.values()) {
      let neighbor: string | null = null
      if (edge.source === nodeId) neighbor = edge.target
      else if (edge.target === nodeId) neighbor = edge.source

      if (neighbor && !path.includes(neighbor)) {
        queue.push({ nodeId: neighbor, path: [...path, neighbor] })
      }
    }
  }

  return paths
}

export function getGraphStats(): GraphStats {
  const nodesByType: Record<string, number> = {}
  const nodesByApp: Record<string, number> = {}
  const edgesByRelationship: Record<string, number> = {}

  for (const node of nodeStore.values()) {
    nodesByType[node.type] = (nodesByType[node.type] || 0) + 1
    nodesByApp[node.app] = (nodesByApp[node.app] || 0) + 1
  }

  for (const edge of edgeStore.values()) {
    edgesByRelationship[edge.relationship] = (edgesByRelationship[edge.relationship] || 0) + 1
  }

  return {
    nodeCount: nodeStore.size,
    edgeCount: edgeStore.size,
    nodesByType,
    nodesByApp,
    edgesByRelationship,
  }
}

// Export store accessors for API endpoints
export function getNode(id: string): GraphNode | undefined {
  return nodeStore.get(id)
}

export function getAllNodes(): GraphNode[] {
  return [...nodeStore.values()]
}

export function getAllEdges(): GraphEdge[] {
  return [...edgeStore.values()]
}
