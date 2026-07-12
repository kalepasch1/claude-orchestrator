<template>
  <div class="p-6">
    <div class="flex items-center justify-between mb-6">
      <div>
        <h2 class="text-xl font-semibold">Fleet Knowledge Graph</h2>
        <p class="text-sm text-gray-500 mt-1">
          Semantic entity graph across all apps. Trace connections through users, documents, transactions, and compliance.
        </p>
      </div>
      <div class="flex gap-2">
        <button
          class="px-4 py-2 text-sm bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-lg transition-colors"
          @click="fetchStats"
        >
          Stats
        </button>
        <button
          class="px-4 py-2 text-sm bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg transition-colors disabled:opacity-50"
          :disabled="loading"
          @click="runSearch"
        >
          {{ loading ? 'Loading...' : 'Search' }}
        </button>
      </div>
    </div>

    <!-- Search bar -->
    <div class="flex gap-3 mb-6">
      <div class="flex-1 relative">
        <input
          v-model="searchInput"
          type="text"
          placeholder="Enter email, entity ID, or keyword..."
          class="w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-2.5 text-sm text-gray-200 placeholder-gray-600 focus:border-indigo-500 focus:outline-none"
          @keydown.enter="runSearch"
        />
      </div>
      <select
        v-model="searchType"
        class="bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-300"
      >
        <option value="email">Email</option>
        <option value="keyword">Keyword</option>
        <option value="nodeId">Node ID</option>
      </select>
      <select
        v-model="filterApp"
        class="bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-300"
      >
        <option value="">All Apps</option>
        <option v-for="a in APP_LIST" :key="a" :value="a">{{ a }}</option>
      </select>
      <select
        v-model="filterType"
        class="bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-300"
      >
        <option value="">All Types</option>
        <option v-for="t in ENTITY_TYPES" :key="t" :value="t">{{ t }}</option>
      </select>
      <div class="flex items-center gap-2">
        <label class="text-xs text-gray-500">Depth</label>
        <input
          v-model.number="maxDepth"
          type="range"
          min="1"
          max="6"
          class="w-20"
        />
        <span class="text-xs text-gray-400 w-4">{{ maxDepth }}</span>
      </div>
    </div>

    <!-- Error state -->
    <div v-if="error" class="bg-red-950/30 border border-red-800/40 rounded-lg p-4 mb-4">
      <div class="text-sm text-red-400">{{ error }}</div>
    </div>

    <!-- Stats bar -->
    <div class="flex gap-4 mb-4">
      <div class="bg-gray-900 border border-gray-800 rounded-lg px-4 py-2 text-center">
        <div class="text-lg font-semibold text-indigo-400">{{ graphData.stats?.totalNodes || 0 }}</div>
        <div class="text-xs text-gray-500">Nodes</div>
      </div>
      <div class="bg-gray-900 border border-gray-800 rounded-lg px-4 py-2 text-center">
        <div class="text-lg font-semibold text-emerald-400">{{ graphData.stats?.totalEdges || 0 }}</div>
        <div class="text-xs text-gray-500">Edges</div>
      </div>
      <div class="bg-gray-900 border border-gray-800 rounded-lg px-4 py-2 text-center">
        <div class="text-lg font-semibold text-amber-400">{{ graphData.stats?.appsTraversed?.length || 0 }}</div>
        <div class="text-xs text-gray-500">Apps</div>
      </div>
      <div v-if="graphData.stats?.appsTraversed?.length" class="flex items-center gap-1 ml-2">
        <span
          v-for="app in graphData.stats.appsTraversed"
          :key="app"
          class="px-2 py-0.5 rounded text-xs font-medium"
          :style="{ backgroundColor: APP_COLORS[app] + '22', color: APP_COLORS[app] }"
        >{{ app }}</span>
      </div>

      <!-- Path finder (right side) -->
      <div class="ml-auto flex items-center gap-2">
        <input
          v-model="pathFrom"
          type="text"
          placeholder="From node ID"
          class="bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs text-gray-300 w-40"
        />
        <span class="text-gray-600 text-xs">&#8594;</span>
        <input
          v-model="pathTo"
          type="text"
          placeholder="To node ID"
          class="bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs text-gray-300 w-40"
        />
        <button
          class="px-3 py-1 text-xs bg-gray-800 hover:bg-gray-700 text-gray-300 rounded transition-colors"
          @click="findPaths"
        >
          Find Path
        </button>
      </div>
    </div>

    <!-- Path results -->
    <div v-if="pathResults.length > 0" class="bg-indigo-950/20 border border-indigo-800/30 rounded-lg p-3 mb-4">
      <div class="text-xs font-medium text-indigo-400 mb-2">Paths Found: {{ pathResults.length }}</div>
      <div v-for="(path, i) in pathResults" :key="i" class="text-xs text-gray-400 mb-1">
        <span class="text-gray-300">{{ path.from }}</span>
        <template v-for="(via, j) in path.via" :key="j">
          <span class="text-gray-600 mx-1">&#8594;</span>
          <span class="text-amber-400">{{ via }}</span>
        </template>
        <span class="text-gray-600 mx-1">&#8594;</span>
        <span class="text-gray-300">{{ path.to }}</span>
      </div>
    </div>

    <div class="grid grid-cols-3 gap-6">
      <!-- Graph visualization (2/3 width) -->
      <div class="col-span-2 bg-gray-900 border border-gray-800 rounded-lg p-4">
        <div class="flex items-center justify-between mb-3">
          <h3 class="text-sm font-medium text-gray-300">Entity Graph</h3>
          <div class="flex gap-2">
            <button
              class="px-2 py-1 text-xs bg-gray-800 hover:bg-gray-700 rounded text-gray-400"
              @click="resetSimulation"
            >
              Reset Layout
            </button>
          </div>
        </div>

        <svg
          ref="svgRef"
          :viewBox="`0 0 ${SVG_WIDTH} ${SVG_HEIGHT}`"
          class="w-full bg-gray-950 rounded-lg"
          style="min-height: 500px"
          @mousedown="onSvgMouseDown"
          @mousemove="onSvgMouseMove"
          @mouseup="onSvgMouseUp"
          @mouseleave="onSvgMouseUp"
        >
          <!-- Grid -->
          <defs>
            <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
              <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#1f2937" stroke-width="0.5" />
            </pattern>
            <!-- Arrow marker -->
            <marker id="arrowhead" markerWidth="6" markerHeight="4" refX="6" refY="2" orient="auto">
              <polygon points="0 0, 6 2, 0 4" fill="#4b5563" />
            </marker>
          </defs>
          <rect width="100%" height="100%" fill="url(#grid)" />

          <!-- Edges -->
          <g v-for="edge in displayEdges" :key="edge.id">
            <line
              :x1="getNodePos(edge.source).x"
              :y1="getNodePos(edge.source).y"
              :x2="getNodePos(edge.target).x"
              :y2="getNodePos(edge.target).y"
              :stroke="EDGE_COLORS[edge.relationship] || '#4b5563'"
              :stroke-width="1 + edge.weight"
              :stroke-dasharray="edge.relationship === 'identity' ? '6,3' : 'none'"
              :opacity="selectedNode && selectedNode.id !== edge.source && selectedNode.id !== edge.target ? 0.15 : 0.6"
              marker-end="url(#arrowhead)"
            />
            <!-- Edge label -->
            <text
              :x="(getNodePos(edge.source).x + getNodePos(edge.target).x) / 2"
              :y="(getNodePos(edge.source).y + getNodePos(edge.target).y) / 2 - 4"
              fill="#6b7280"
              font-size="8"
              text-anchor="middle"
              :opacity="selectedNode && selectedNode.id !== edge.source && selectedNode.id !== edge.target ? 0.1 : 0.5"
            >{{ edge.relationship }}</text>
          </g>

          <!-- Nodes -->
          <g
            v-for="node in displayNodes"
            :key="node.id"
            class="cursor-pointer"
            @mousedown.stop="onNodeMouseDown($event, node)"
            @click.stop="selectNode(node)"
          >
            <!-- Glow ring for selected -->
            <circle
              v-if="selectedNode?.id === node.id"
              :cx="getNodePos(node.id).x"
              :cy="getNodePos(node.id).y"
              :r="NODE_SIZES[node.type] + 8"
              :fill="APP_COLORS[node.app] || '#9ca3af'"
              opacity="0.15"
            >
              <animate attributeName="r" :values="`${NODE_SIZES[node.type] + 6};${NODE_SIZES[node.type] + 12};${NODE_SIZES[node.type] + 6}`" dur="2s" repeatCount="indefinite" />
            </circle>

            <!-- Node circle -->
            <circle
              :cx="getNodePos(node.id).x"
              :cy="getNodePos(node.id).y"
              :r="NODE_SIZES[node.type] || 12"
              :fill="selectedNode?.id === node.id ? (APP_COLORS[node.app] || '#9ca3af') : 'transparent'"
              :stroke="APP_COLORS[node.app] || '#9ca3af'"
              :stroke-width="node.type === 'user' ? 3 : 2"
              :opacity="selectedNode && selectedNode.id !== node.id ? 0.4 : 1"
            />

            <!-- Type icon -->
            <text
              :x="getNodePos(node.id).x"
              :y="getNodePos(node.id).y + 4"
              fill="white"
              :font-size="NODE_SIZES[node.type] > 14 ? 12 : 9"
              text-anchor="middle"
              pointer-events="none"
            >{{ TYPE_ICONS[node.type] || '?' }}</text>

            <!-- Label -->
            <text
              :x="getNodePos(node.id).x"
              :y="getNodePos(node.id).y + (NODE_SIZES[node.type] || 12) + 12"
              fill="#d1d5db"
              font-size="9"
              text-anchor="middle"
              pointer-events="none"
              :opacity="selectedNode && selectedNode.id !== node.id ? 0.3 : 0.9"
            >{{ truncateLabel(node.label) }}</text>

            <!-- App badge -->
            <text
              :x="getNodePos(node.id).x"
              :y="getNodePos(node.id).y - (NODE_SIZES[node.type] || 12) - 4"
              :fill="APP_COLORS[node.app] || '#9ca3af'"
              font-size="7"
              text-anchor="middle"
              pointer-events="none"
              :opacity="0.6"
            >{{ node.app }}</text>
          </g>

          <!-- Hover tooltip -->
          <g v-if="hoveredNode" pointer-events="none">
            <rect
              :x="getNodePos(hoveredNode.id).x + 20"
              :y="getNodePos(hoveredNode.id).y - 30"
              :width="180"
              :height="50"
              fill="#111827"
              stroke="#374151"
              rx="4"
            />
            <text
              :x="getNodePos(hoveredNode.id).x + 28"
              :y="getNodePos(hoveredNode.id).y - 14"
              fill="#e5e7eb"
              font-size="10"
            >{{ hoveredNode.type }}: {{ hoveredNode.entityId }}</text>
            <text
              :x="getNodePos(hoveredNode.id).x + 28"
              :y="getNodePos(hoveredNode.id).y + 2"
              fill="#9ca3af"
              font-size="8"
            >{{ hoveredNode.app }} | {{ hoveredNode.lastUpdated?.slice(0, 10) }}</text>
          </g>

          <!-- Empty state -->
          <text
            v-if="displayNodes.length === 0 && !loading"
            x="400"
            y="250"
            fill="#4b5563"
            font-size="14"
            text-anchor="middle"
          >Search for an email or keyword to explore the knowledge graph</text>
        </svg>

        <!-- Legend -->
        <div class="flex flex-wrap gap-4 mt-3 px-2">
          <div class="text-xs text-gray-600 font-medium">Apps:</div>
          <div v-for="(color, app) in APP_COLORS" :key="app" class="flex items-center gap-1">
            <span class="w-2.5 h-2.5 rounded-full inline-block" :style="{ backgroundColor: color }" />
            <span class="text-xs text-gray-500">{{ app }}</span>
          </div>
          <div class="text-xs text-gray-600 font-medium ml-4">Types:</div>
          <div v-for="(icon, type) in TYPE_ICONS" :key="type" class="flex items-center gap-1">
            <span class="text-xs">{{ icon }}</span>
            <span class="text-xs text-gray-500">{{ type }}</span>
          </div>
        </div>
      </div>

      <!-- Sidebar: selected node details -->
      <div class="space-y-4">
        <!-- Selected node panel -->
        <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
          <h3 class="text-sm font-medium text-gray-300 mb-3">Node Details</h3>
          <div v-if="selectedNode" class="space-y-3">
            <div>
              <div class="text-xs text-gray-500">Label</div>
              <div class="text-sm text-gray-200">{{ selectedNode.label }}</div>
            </div>
            <div class="flex gap-4">
              <div>
                <div class="text-xs text-gray-500">App</div>
                <span
                  class="text-xs font-medium px-2 py-0.5 rounded"
                  :style="{ backgroundColor: APP_COLORS[selectedNode.app] + '22', color: APP_COLORS[selectedNode.app] }"
                >{{ selectedNode.app }}</span>
              </div>
              <div>
                <div class="text-xs text-gray-500">Type</div>
                <div class="text-sm text-gray-300">{{ TYPE_ICONS[selectedNode.type] }} {{ selectedNode.type }}</div>
              </div>
            </div>
            <div>
              <div class="text-xs text-gray-500">Entity ID</div>
              <div class="text-xs text-gray-400 font-mono break-all">{{ selectedNode.entityId }}</div>
            </div>
            <div>
              <div class="text-xs text-gray-500">Node ID</div>
              <div class="text-xs text-gray-400 font-mono break-all">{{ selectedNode.id }}</div>
            </div>
            <div>
              <div class="text-xs text-gray-500">Last Updated</div>
              <div class="text-xs text-gray-400">{{ selectedNode.lastUpdated }}</div>
            </div>

            <!-- Properties -->
            <div>
              <div class="text-xs text-gray-500 mb-1">Properties</div>
              <div class="bg-gray-950 rounded p-2 max-h-48 overflow-y-auto">
                <div v-for="(val, key) in selectedNode.properties" :key="key" class="text-xs mb-1">
                  <span class="text-gray-500">{{ key }}:</span>
                  <span class="text-gray-300 ml-1">{{ typeof val === 'object' ? JSON.stringify(val) : val }}</span>
                </div>
              </div>
            </div>

            <!-- Connected nodes -->
            <div>
              <div class="text-xs text-gray-500 mb-1">Connected ({{ connectedNodes.length }})</div>
              <div class="space-y-1 max-h-36 overflow-y-auto">
                <div
                  v-for="cn in connectedNodes"
                  :key="cn.node.id"
                  class="flex items-center gap-2 p-1.5 rounded bg-gray-950 hover:bg-gray-800 cursor-pointer text-xs"
                  @click="selectNode(cn.node)"
                >
                  <span
                    class="w-2 h-2 rounded-full"
                    :style="{ backgroundColor: APP_COLORS[cn.node.app] || '#9ca3af' }"
                  />
                  <span class="text-gray-300 truncate flex-1">{{ cn.node.label }}</span>
                  <span class="text-gray-600">{{ cn.relationship }}</span>
                </div>
              </div>
            </div>

            <!-- Actions -->
            <div class="flex gap-2">
              <button
                class="px-3 py-1.5 text-xs bg-indigo-600 hover:bg-indigo-500 text-white rounded transition-colors"
                @click="expandNode(selectedNode)"
              >
                Expand
              </button>
              <button
                class="px-3 py-1.5 text-xs bg-gray-800 hover:bg-gray-700 text-gray-300 rounded transition-colors"
                @click="useAsPathEndpoint(selectedNode)"
              >
                Use in Path
              </button>
            </div>
          </div>
          <div v-else class="text-sm text-gray-600">Click a node to see details</div>
        </div>

        <!-- Graph stats -->
        <div v-if="globalStats" class="bg-gray-900 border border-gray-800 rounded-lg p-4">
          <h3 class="text-sm font-medium text-gray-300 mb-3">Graph Statistics</h3>
          <div class="grid grid-cols-2 gap-2">
            <div class="text-center p-2 bg-gray-950 rounded">
              <div class="text-sm font-semibold text-gray-200">{{ globalStats.nodeCount }}</div>
              <div class="text-xs text-gray-500">Total Nodes</div>
            </div>
            <div class="text-center p-2 bg-gray-950 rounded">
              <div class="text-sm font-semibold text-gray-200">{{ globalStats.edgeCount }}</div>
              <div class="text-xs text-gray-500">Total Edges</div>
            </div>
          </div>
          <div v-if="Object.keys(globalStats.nodesByApp || {}).length" class="mt-3">
            <div class="text-xs text-gray-500 mb-1">By App</div>
            <div v-for="(count, app) in globalStats.nodesByApp" :key="app" class="flex justify-between text-xs py-0.5">
              <span :style="{ color: APP_COLORS[app as string] || '#9ca3af' }">{{ app }}</span>
              <span class="text-gray-400">{{ count }}</span>
            </div>
          </div>
          <div v-if="Object.keys(globalStats.nodesByType || {}).length" class="mt-3">
            <div class="text-xs text-gray-500 mb-1">By Type</div>
            <div v-for="(count, type) in globalStats.nodesByType" :key="type" class="flex justify-between text-xs py-0.5">
              <span class="text-gray-300">{{ TYPE_ICONS[type as string] || '' }} {{ type }}</span>
              <span class="text-gray-400">{{ count }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
definePageMeta({ layout: 'admin' })

// ── Constants ──────────────────────────────────────────────────────────
const SVG_WIDTH = 800
const SVG_HEIGHT = 500

const APP_LIST = ['apparently', 'tomorrow', 'smarter', 'galop', 'hisanta', 'pareto', 'orchestrator']
const ENTITY_TYPES = ['user', 'document', 'transaction', 'feature', 'policy', 'incident', 'approval', 'workspace']

const APP_COLORS: Record<string, string> = {
  apparently: '#8b5cf6',
  tomorrow: '#f59e0b',
  smarter: '#3b82f6',
  galop: '#10b981',
  hisanta: '#ef4444',
  pareto: '#ec4899',
  orchestrator: '#6366f1',
}

const EDGE_COLORS: Record<string, string> = {
  identity: '#a78bfa',
  created_by: '#60a5fa',
  owns: '#34d399',
  approved: '#fbbf24',
  flagged: '#f87171',
  references: '#9ca3af',
  part_of: '#818cf8',
  triggered: '#fb923c',
}

const NODE_SIZES: Record<string, number> = {
  user: 18,
  workspace: 16,
  document: 14,
  transaction: 14,
  feature: 12,
  policy: 14,
  incident: 14,
  approval: 12,
}

const TYPE_ICONS: Record<string, string> = {
  user: '\u{1F464}',
  document: '\u{1F4C4}',
  transaction: '\u{1F4B3}',
  feature: '\u{2699}',
  policy: '\u{1F4CB}',
  incident: '\u{26A0}',
  approval: '\u{2705}',
  workspace: '\u{1F3E2}',
}

// ── State ──────────────────────────────────────────────────────────────
const searchInput = ref('')
const searchType = ref<'email' | 'keyword' | 'nodeId'>('email')
const filterApp = ref('')
const filterType = ref('')
const maxDepth = ref(3)
const loading = ref(false)
const error = ref('')

interface GNode { id: string; app: string; type: string; entityId: string; label: string; properties: Record<string, any>; lastUpdated: string }
interface GEdge { id: string; source: string; target: string; relationship: string; weight: number; metadata?: Record<string, any> }

const graphData = ref<{ nodes: GNode[]; edges: GEdge[]; stats: any }>({ nodes: [], edges: [], stats: {} })
const selectedNode = ref<GNode | null>(null)
const hoveredNode = ref<GNode | null>(null)
const globalStats = ref<any>(null)

// Path finder
const pathFrom = ref('')
const pathTo = ref('')
const pathResults = ref<any[]>([])

// Force simulation positions
const nodePositions = ref<Map<string, { x: number; y: number; vx: number; vy: number }>>(new Map())
const svgRef = ref<SVGElement | null>(null)

// Dragging
const dragTarget = ref<string | null>(null)
const isDragging = ref(false)
let animFrameId: number | null = null

// ── Computed ───────────────────────────────────────────────────────────
const displayNodes = computed(() => graphData.value.nodes || [])
const displayEdges = computed(() => graphData.value.edges || [])

const connectedNodes = computed(() => {
  if (!selectedNode.value) return []
  const results: { node: GNode; relationship: string }[] = []
  const edges = graphData.value.edges || []
  const nodes = graphData.value.nodes || []
  const nodeMap = new Map(nodes.map(n => [n.id, n]))

  for (const edge of edges) {
    if (edge.source === selectedNode.value.id) {
      const target = nodeMap.get(edge.target)
      if (target) results.push({ node: target, relationship: edge.relationship })
    } else if (edge.target === selectedNode.value.id) {
      const source = nodeMap.get(edge.source)
      if (source) results.push({ node: source, relationship: edge.relationship })
    }
  }
  return results
})

// ── Force simulation ───────────────────────────────────────────────────
function initPositions() {
  const pos = new Map<string, { x: number; y: number; vx: number; vy: number }>()
  const nodes = graphData.value.nodes || []

  // Group by app for initial layout
  const appGroups = new Map<string, GNode[]>()
  for (const node of nodes) {
    const list = appGroups.get(node.app) || []
    list.push(node)
    appGroups.set(node.app, list)
  }

  const appKeys = [...appGroups.keys()]
  const cx = SVG_WIDTH / 2
  const cy = SVG_HEIGHT / 2
  const radius = Math.min(SVG_WIDTH, SVG_HEIGHT) * 0.3

  let appIdx = 0
  for (const [, appNodes] of appGroups) {
    const appAngle = (2 * Math.PI * appIdx) / Math.max(appKeys.length, 1)
    const appCx = cx + radius * Math.cos(appAngle)
    const appCy = cy + radius * Math.sin(appAngle)

    for (let i = 0; i < appNodes.length; i++) {
      const spread = 40
      const angle = (2 * Math.PI * i) / Math.max(appNodes.length, 1)
      pos.set(appNodes[i].id, {
        x: appCx + spread * Math.cos(angle) + (Math.random() - 0.5) * 20,
        y: appCy + spread * Math.sin(angle) + (Math.random() - 0.5) * 20,
        vx: 0,
        vy: 0,
      })
    }
    appIdx++
  }

  nodePositions.value = pos
}

function runSimulation() {
  const nodes = graphData.value.nodes || []
  const edges = graphData.value.edges || []
  const pos = nodePositions.value
  if (nodes.length === 0) return

  let frame = 0
  const maxFrames = 200
  const damping = 0.85
  const repulsion = 2000
  const attraction = 0.02
  const centerPull = 0.005

  function step() {
    frame++
    let totalMovement = 0

    // Repulsion between all node pairs
    for (let i = 0; i < nodes.length; i++) {
      const a = pos.get(nodes[i].id)
      if (!a) continue
      for (let j = i + 1; j < nodes.length; j++) {
        const b = pos.get(nodes[j].id)
        if (!b) continue

        const dx = a.x - b.x
        const dy = a.y - b.y
        const dist = Math.sqrt(dx * dx + dy * dy) || 1
        const force = repulsion / (dist * dist)
        const fx = (dx / dist) * force
        const fy = (dy / dist) * force

        a.vx += fx
        a.vy += fy
        b.vx -= fx
        b.vy -= fy
      }
    }

    // Attraction along edges
    for (const edge of edges) {
      const a = pos.get(edge.source)
      const b = pos.get(edge.target)
      if (!a || !b) continue

      const dx = b.x - a.x
      const dy = b.y - a.y
      const dist = Math.sqrt(dx * dx + dy * dy) || 1
      const force = attraction * dist
      const fx = (dx / dist) * force
      const fy = (dy / dist) * force

      a.vx += fx
      a.vy += fy
      b.vx -= fx
      b.vy -= fy
    }

    // Center gravity + apply velocity
    const cx = SVG_WIDTH / 2
    const cy = SVG_HEIGHT / 2
    for (const node of nodes) {
      const p = pos.get(node.id)
      if (!p || node.id === dragTarget.value) continue

      p.vx += (cx - p.x) * centerPull
      p.vy += (cy - p.y) * centerPull

      p.vx *= damping
      p.vy *= damping

      p.x += p.vx
      p.y += p.vy

      // Boundary clamping
      p.x = Math.max(40, Math.min(SVG_WIDTH - 40, p.x))
      p.y = Math.max(40, Math.min(SVG_HEIGHT - 40, p.y))

      totalMovement += Math.abs(p.vx) + Math.abs(p.vy)
    }

    // Force reactivity update
    nodePositions.value = new Map(pos)

    if (frame < maxFrames && totalMovement > 0.5) {
      animFrameId = requestAnimationFrame(step)
    }
  }

  if (animFrameId) cancelAnimationFrame(animFrameId)
  animFrameId = requestAnimationFrame(step)
}

function getNodePos(nodeId: string): { x: number; y: number } {
  const p = nodePositions.value.get(nodeId)
  return p ? { x: p.x, y: p.y } : { x: SVG_WIDTH / 2, y: SVG_HEIGHT / 2 }
}

function resetSimulation() {
  initPositions()
  runSimulation()
}

// ── SVG Interaction ────────────────────────────────────────────────────
function getSvgCoords(event: MouseEvent): { x: number; y: number } {
  const svg = svgRef.value
  if (!svg) return { x: 0, y: 0 }
  const rect = svg.getBoundingClientRect()
  return {
    x: ((event.clientX - rect.left) / rect.width) * SVG_WIDTH,
    y: ((event.clientY - rect.top) / rect.height) * SVG_HEIGHT,
  }
}

function onNodeMouseDown(event: MouseEvent, node: GNode) {
  dragTarget.value = node.id
  isDragging.value = true
  event.preventDefault()
}

function onSvgMouseDown(_event: MouseEvent) {
  // Deselect if clicking background
}

function onSvgMouseMove(event: MouseEvent) {
  if (!isDragging.value || !dragTarget.value) return
  const coords = getSvgCoords(event)
  const pos = nodePositions.value.get(dragTarget.value)
  if (pos) {
    pos.x = coords.x
    pos.y = coords.y
    pos.vx = 0
    pos.vy = 0
    nodePositions.value = new Map(nodePositions.value)
  }
}

function onSvgMouseUp() {
  dragTarget.value = null
  isDragging.value = false
}

// ── API calls ──────────────────────────────────────────────────────────
async function runSearch() {
  if (!searchInput.value.trim()) return
  loading.value = true
  error.value = ''

  try {
    const params: Record<string, string> = {}
    if (searchType.value === 'email') params.email = searchInput.value
    else if (searchType.value === 'keyword') params.keyword = searchInput.value
    else if (searchType.value === 'nodeId') params.nodeId = searchInput.value

    if (filterApp.value) params.app = filterApp.value
    if (filterType.value) params.type = filterType.value
    params.depth = String(maxDepth.value)
    params.limit = '50'

    // First, trigger a build if searching by email
    if (searchType.value === 'email') {
      await $fetch('/api/admin/knowledge-graph/build', {
        method: 'POST',
        body: { email: searchInput.value },
      })
    }

    const data = await $fetch<any>('/api/admin/knowledge-graph', { params })
    graphData.value = data
    selectedNode.value = null

    initPositions()
    nextTick(() => runSimulation())
  } catch (e: any) {
    error.value = e.data?.message || e.message || 'Search failed'
  } finally {
    loading.value = false
  }
}

async function fetchStats() {
  try {
    const data = await $fetch<any>('/api/admin/knowledge-graph/stats')
    globalStats.value = data
  } catch (e: any) {
    error.value = e.data?.message || e.message || 'Failed to fetch stats'
  }
}

async function findPaths() {
  if (!pathFrom.value || !pathTo.value) return
  try {
    const data = await $fetch<any>('/api/admin/knowledge-graph/paths', {
      params: { from: pathFrom.value, to: pathTo.value },
    })
    pathResults.value = data.paths || []
  } catch (e: any) {
    error.value = e.data?.message || e.message || 'Path search failed'
  }
}

async function expandNode(node: GNode) {
  loading.value = true
  error.value = ''
  try {
    await $fetch('/api/admin/knowledge-graph/build', {
      method: 'POST',
      body: { app: node.app, type: node.type, entityId: node.entityId },
    })

    const data = await $fetch<any>('/api/admin/knowledge-graph', {
      params: { nodeId: node.id, depth: String(maxDepth.value), limit: '50' },
    })

    // Merge new nodes/edges into existing graph
    const existingNodeIds = new Set(graphData.value.nodes.map(n => n.id))
    const existingEdgeIds = new Set(graphData.value.edges.map(e => e.id))

    for (const n of (data.nodes || [])) {
      if (!existingNodeIds.has(n.id)) {
        graphData.value.nodes.push(n)
        existingNodeIds.add(n.id)
      }
    }
    for (const e of (data.edges || [])) {
      if (!existingEdgeIds.has(e.id)) {
        graphData.value.edges.push(e)
        existingEdgeIds.add(e.id)
      }
    }

    // Update stats
    graphData.value.stats = {
      totalNodes: graphData.value.nodes.length,
      totalEdges: graphData.value.edges.length,
      appsTraversed: [...new Set(graphData.value.nodes.map(n => n.app))],
    }

    // Re-initialize positions for new nodes only
    const pos = nodePositions.value
    for (const n of graphData.value.nodes) {
      if (!pos.has(n.id)) {
        const basePos = getNodePos(node.id)
        pos.set(n.id, {
          x: basePos.x + (Math.random() - 0.5) * 80,
          y: basePos.y + (Math.random() - 0.5) * 80,
          vx: 0,
          vy: 0,
        })
      }
    }
    nodePositions.value = new Map(pos)
    runSimulation()
  } catch (e: any) {
    error.value = e.data?.message || e.message || 'Expand failed'
  } finally {
    loading.value = false
  }
}

function selectNode(node: GNode) {
  selectedNode.value = node
}

function useAsPathEndpoint(node: GNode) {
  if (!pathFrom.value) pathFrom.value = node.id
  else pathTo.value = node.id
}

function truncateLabel(label: string): string {
  return label.length > 24 ? label.slice(0, 22) + '...' : label
}

// ── Lifecycle ──────────────────────────────────────────────────────────
onMounted(() => {
  fetchStats()
})

onUnmounted(() => {
  if (animFrameId) cancelAnimationFrame(animFrameId)
})
</script>
