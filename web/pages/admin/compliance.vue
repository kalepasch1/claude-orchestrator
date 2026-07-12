<template>
  <div class="p-6">
    <div class="flex items-center justify-between mb-6">
      <div>
        <h2 class="text-xl font-semibold">Compliance Graph</h2>
        <p class="text-sm text-gray-500 mt-1">
          Cross-app dependency map for regulatory actions. Trace compliance impact across the fleet.
        </p>
      </div>
      <button
        class="px-4 py-2 text-sm bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg transition-colors disabled:opacity-50"
        :disabled="loading"
        @click="fetchGraph"
      >
        {{ loading ? 'Loading...' : 'Refresh' }}
      </button>
    </div>

    <!-- Error state -->
    <div v-if="error" class="bg-red-950/30 border border-red-800/40 rounded-lg p-4 mb-4">
      <div class="text-sm text-red-400">{{ error }}</div>
    </div>

    <div class="grid grid-cols-3 gap-6">
      <!-- Graph visualization (2/3 width) -->
      <div class="col-span-2 bg-gray-900 border border-gray-800 rounded-lg p-4">
        <h3 class="text-sm font-medium text-gray-300 mb-3">Dependency Graph</h3>
        <svg
          viewBox="0 0 800 600"
          class="w-full"
          xmlns="http://www.w3.org/2000/svg"
          style="min-height: 400px"
        >
          <!-- Edges -->
          <g v-for="(edge, i) in graphEdges" :key="'edge-' + i">
            <line
              :x1="getNodePosition(edge.source.app, edge.source.entity).x"
              :y1="getNodePosition(edge.source.app, edge.source.entity).y"
              :x2="getNodePosition(edge.target.app, edge.target.entity).x"
              :y2="getNodePosition(edge.target.app, edge.target.entity).y"
              :stroke="edge.propagation === 'auto' ? '#6b7280' : '#4b5563'"
              :stroke-width="edge.propagation === 'auto' ? 2 : 1.5"
              :stroke-dasharray="edge.propagation === 'manual' ? '6,4' : 'none'"
              :opacity="isEdgeHighlighted(edge) ? 1 : 0.4"
            />
            <!-- Arrow marker -->
            <polygon
              :points="getArrowPoints(edge)"
              :fill="edge.propagation === 'auto' ? '#6b7280' : '#4b5563'"
              :opacity="isEdgeHighlighted(edge) ? 1 : 0.4"
            />
          </g>

          <!-- Nodes -->
          <g
            v-for="(node, i) in graphNodes"
            :key="'node-' + i"
            class="cursor-pointer"
          >
            <!-- Glow ring for affected nodes -->
            <circle
              v-if="isNodeAffected(node)"
              :cx="getNodePosition(node.app, node.entity).x"
              :cy="getNodePosition(node.app, node.entity).y"
              :r="32"
              :fill="APP_COLORS[node.app] || '#9ca3af'"
              opacity="0.2"
            >
              <animate attributeName="r" values="30;36;30" dur="1.5s" repeatCount="indefinite" />
              <animate attributeName="opacity" values="0.2;0.05;0.2" dur="1.5s" repeatCount="indefinite" />
            </circle>

            <!-- Node circle -->
            <circle
              :cx="getNodePosition(node.app, node.entity).x"
              :cy="getNodePosition(node.app, node.entity).y"
              :r="24"
              :fill="isNodeAffected(node) ? APP_COLORS[node.app] || '#9ca3af' : 'transparent'"
              :stroke="APP_COLORS[node.app] || '#9ca3af'"
              :stroke-width="isNodeAffected(node) ? 3 : 2"
              :opacity="hasAnalysis && !isNodeAffected(node) && !isNodeTrigger(node) ? 0.3 : 1"
            />

            <!-- Trigger ring -->
            <circle
              v-if="isNodeTrigger(node)"
              :cx="getNodePosition(node.app, node.entity).x"
              :cy="getNodePosition(node.app, node.entity).y"
              :r="28"
              fill="none"
              stroke="#facc15"
              stroke-width="2"
              stroke-dasharray="4,3"
            >
              <animateTransform attributeName="transform" type="rotate"
                :values="`0 ${getNodePosition(node.app, node.entity).x} ${getNodePosition(node.app, node.entity).y}; 360 ${getNodePosition(node.app, node.entity).x} ${getNodePosition(node.app, node.entity).y}`"
                dur="8s" repeatCount="indefinite" />
            </circle>

            <!-- App label -->
            <text
              :x="getNodePosition(node.app, node.entity).x"
              :y="getNodePosition(node.app, node.entity).y - 4"
              text-anchor="middle"
              class="text-[10px] font-medium fill-gray-200 select-none pointer-events-none"
            >{{ node.app }}</text>

            <!-- Entity label -->
            <text
              :x="getNodePosition(node.app, node.entity).x"
              :y="getNodePosition(node.app, node.entity).y + 8"
              text-anchor="middle"
              class="text-[8px] fill-gray-400 select-none pointer-events-none"
            >{{ node.entity }}</text>
          </g>
        </svg>

        <!-- Legend -->
        <div class="flex flex-wrap gap-4 mt-4 pt-3 border-t border-gray-800">
          <div v-for="(color, app) in APP_COLORS" :key="app" class="flex items-center gap-1.5">
            <span class="w-3 h-3 rounded-full" :style="{ backgroundColor: color }"></span>
            <span class="text-xs text-gray-400">{{ app }}</span>
          </div>
          <div class="flex items-center gap-1.5 ml-4">
            <span class="w-6 border-t-2 border-gray-500"></span>
            <span class="text-xs text-gray-500">auto</span>
          </div>
          <div class="flex items-center gap-1.5">
            <span class="w-6 border-t-2 border-dashed border-gray-600"></span>
            <span class="text-xs text-gray-500">manual</span>
          </div>
        </div>
      </div>

      <!-- Impact analysis panel (1/3 width) -->
      <div class="space-y-4">
        <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
          <h3 class="text-sm font-medium text-gray-300 mb-3">Impact Analysis</h3>

          <div class="space-y-3">
            <div>
              <label class="text-xs text-gray-500 block mb-1">Trigger App</label>
              <select
                v-model="triggerApp"
                class="w-full bg-gray-800 border border-gray-700 text-gray-200 text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-indigo-500"
              >
                <option value="">Select app...</option>
                <option v-for="app in appList" :key="app" :value="app">{{ app }}</option>
              </select>
            </div>

            <div>
              <label class="text-xs text-gray-500 block mb-1">Entity Type</label>
              <select
                v-model="entityType"
                class="w-full bg-gray-800 border border-gray-700 text-gray-200 text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-indigo-500"
              >
                <option value="">Select entity...</option>
                <option value="user">user</option>
                <option value="document">document</option>
                <option value="transaction">transaction</option>
                <option value="feature">feature</option>
              </select>
            </div>

            <div>
              <label class="text-xs text-gray-500 block mb-1">Trigger Action</label>
              <select
                v-model="triggerAction"
                class="w-full bg-gray-800 border border-gray-700 text-gray-200 text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-indigo-500"
              >
                <option value="">Select action...</option>
                <option value="flagged">flagged</option>
                <option value="suspended">suspended</option>
                <option value="blocked">blocked</option>
              </select>
            </div>

            <div>
              <label class="text-xs text-gray-500 block mb-1">Entity ID (optional)</label>
              <input
                v-model="entityId"
                placeholder="e.g. user-123"
                class="w-full bg-gray-800 border border-gray-700 text-gray-200 text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-indigo-500"
              />
            </div>

            <button
              class="w-full px-4 py-2 text-sm bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg transition-colors disabled:opacity-50"
              :disabled="!triggerApp || !triggerAction || !entityType || analyzing"
              @click="runAnalysis"
            >
              {{ analyzing ? 'Analyzing...' : 'Run Analysis' }}
            </button>
          </div>
        </div>

        <!-- Analysis results -->
        <div v-if="analysis" class="bg-gray-900 border border-gray-800 rounded-lg p-4">
          <h3 class="text-sm font-medium text-gray-300 mb-3">
            Suggested Actions
            <span class="text-xs text-gray-500 font-normal ml-2">{{ analysis.affectedNodes.length }} affected</span>
          </h3>

          <div v-if="analysis.suggestedActions.length === 0" class="text-xs text-gray-500">
            No downstream impact detected.
          </div>

          <div v-else class="space-y-2">
            <div
              v-for="(action, i) in analysis.suggestedActions"
              :key="i"
              class="bg-gray-800 border border-gray-700 rounded-lg p-3"
            >
              <div class="flex items-center gap-2 mb-1">
                <span class="text-sm font-medium text-gray-200">{{ action.app }}</span>
                <span
                  class="text-xs px-1.5 py-0.5 rounded font-medium"
                  :class="action.auto ? 'bg-green-900/50 text-green-300' : 'bg-yellow-900/50 text-yellow-300'"
                >
                  {{ action.auto ? 'AUTO' : 'MANUAL' }}
                </span>
              </div>
              <div class="text-xs text-gray-400 font-mono mb-1">{{ action.action }}</div>
              <div class="text-xs text-gray-500">{{ action.reason }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Impact history -->
    <div class="mt-6 bg-gray-900 border border-gray-800 rounded-lg p-4">
      <h3 class="text-sm font-medium text-gray-300 mb-3">Impact History</h3>

      <div v-if="history.length === 0" class="text-xs text-gray-500">
        No impact analyses have been run yet.
      </div>

      <div v-else class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="text-xs text-gray-500 uppercase tracking-wider border-b border-gray-800">
              <th class="text-left pb-2 pr-4">Timestamp</th>
              <th class="text-left pb-2 pr-4">Trigger App</th>
              <th class="text-left pb-2 pr-4">Action</th>
              <th class="text-left pb-2 pr-4">Entity</th>
              <th class="text-left pb-2 pr-4">Affected</th>
              <th class="text-left pb-2">Auto / Manual</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(entry, i) in history"
              :key="i"
              class="border-b border-gray-800/50 hover:bg-gray-800/30 cursor-pointer"
              @click="replayAnalysis(entry)"
            >
              <td class="py-2 pr-4 text-xs text-gray-500 font-mono">{{ formatTime(entry.timestamp) }}</td>
              <td class="py-2 pr-4">
                <span class="inline-flex items-center gap-1.5">
                  <span class="w-2 h-2 rounded-full" :style="{ backgroundColor: APP_COLORS[entry.triggerApp] || '#9ca3af' }"></span>
                  <span class="text-gray-300">{{ entry.triggerApp }}</span>
                </span>
              </td>
              <td class="py-2 pr-4">
                <span
                  class="text-xs px-1.5 py-0.5 rounded"
                  :class="{
                    'bg-yellow-900/50 text-yellow-300': entry.triggerAction === 'flagged',
                    'bg-orange-900/50 text-orange-300': entry.triggerAction === 'suspended',
                    'bg-red-900/50 text-red-300': entry.triggerAction === 'blocked',
                  }"
                >{{ entry.triggerAction }}</span>
              </td>
              <td class="py-2 pr-4 text-gray-400">{{ entry.affectedNodes[0]?.entity || '-' }}</td>
              <td class="py-2 pr-4 text-gray-300">{{ entry.affectedNodes.length }}</td>
              <td class="py-2">
                <span class="text-green-400">{{ entry.suggestedActions.filter(a => a.auto).length }}</span>
                <span class="text-gray-600"> / </span>
                <span class="text-yellow-400">{{ entry.suggestedActions.filter(a => !a.auto).length }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
definePageMeta({ layout: 'admin' })

interface ComplianceNode {
  app: string
  entity: string
  entityId?: string
  status: 'clean' | 'flagged' | 'suspended' | 'blocked'
}

interface ComplianceEdge {
  source: { app: string; entity: string }
  target: { app: string; entity: string }
  relationship: 'owns' | 'references' | 'depends_on' | 'mirrors'
  propagation: 'auto' | 'manual'
}

interface ImpactAnalysis {
  triggerApp: string
  triggerAction: string
  affectedNodes: ComplianceNode[]
  suggestedActions: { app: string; action: string; reason: string; auto: boolean }[]
  timestamp: string
}

interface GraphResponse {
  nodes: ComplianceNode[]
  edges: ComplianceEdge[]
  history: ImpactAnalysis[]
  timestamp: string
}

const APP_COLORS: Record<string, string> = {
  apparently: '#818cf8',
  tomorrow: '#f472b6',
  smarter: '#34d399',
  galop: '#fbbf24',
  hisanta: '#f87171',
  pareto: '#60a5fa',
  orchestrator: '#a78bfa',
}

const appList = ['apparently', 'tomorrow', 'smarter', 'galop', 'hisanta', 'pareto', 'orchestrator']

// State
const graphNodes = ref<ComplianceNode[]>([])
const graphEdges = ref<ComplianceEdge[]>([])
const history = ref<ImpactAnalysis[]>([])
const loading = ref(false)
const error = ref<string | null>(null)

// Analysis form
const triggerApp = ref('')
const triggerAction = ref('')
const entityType = ref('')
const entityId = ref('')
const analyzing = ref(false)
const analysis = ref<ImpactAnalysis | null>(null)
const hasAnalysis = computed(() => analysis.value !== null)

// Node positioning — deterministic layout
// Build unique positions: group by app, spread entities within each app's arc segment
const nodePositionCache = new Map<string, { x: number; y: number }>()

function buildPositions(nodes: ComplianceNode[]) {
  nodePositionCache.clear()
  const cx = 400
  const cy = 300
  const radius = 220

  // Group nodes by app
  const appGroups = new Map<string, string[]>()
  for (const node of nodes) {
    const entities = appGroups.get(node.app) || []
    if (!entities.includes(node.entity)) entities.push(node.entity)
    appGroups.set(node.app, entities)
  }

  // Place orchestrator in center
  const orch = appGroups.get('orchestrator')
  if (orch) {
    for (let j = 0; j < orch.length; j++) {
      const offset = (j - (orch.length - 1) / 2) * 30
      nodePositionCache.set(`orchestrator:${orch[j]}`, { x: cx + offset, y: cy })
    }
    appGroups.delete('orchestrator')
  }

  // Distribute remaining apps around the circle
  const apps = Array.from(appGroups.keys()).sort()
  const angleStep = (2 * Math.PI) / Math.max(apps.length, 1)

  apps.forEach((app, i) => {
    const baseAngle = angleStep * i - Math.PI / 2 // start from top
    const entities = appGroups.get(app)!
    for (let j = 0; j < entities.length; j++) {
      const entityOffset = (j - (entities.length - 1) / 2) * 0.12
      const angle = baseAngle + entityOffset
      const r = radius + j * 15
      nodePositionCache.set(`${app}:${entities[j]}`, {
        x: cx + r * Math.cos(angle),
        y: cy + r * Math.sin(angle),
      })
    }
  })
}

function getNodePosition(app: string, entity: string): { x: number; y: number } {
  return nodePositionCache.get(`${app}:${entity}`) || { x: 400, y: 300 }
}

function getArrowPoints(edge: ComplianceEdge): string {
  const s = getNodePosition(edge.source.app, edge.source.entity)
  const t = getNodePosition(edge.target.app, edge.target.entity)
  const dx = t.x - s.x
  const dy = t.y - s.y
  const dist = Math.sqrt(dx * dx + dy * dy)
  if (dist === 0) return ''
  const ux = dx / dist
  const uy = dy / dist
  // Arrow tip at edge of target circle (r=24)
  const tipX = t.x - ux * 26
  const tipY = t.y - uy * 26
  const baseX = tipX - ux * 8
  const baseY = tipY - uy * 8
  const perpX = -uy * 4
  const perpY = ux * 4
  return `${tipX},${tipY} ${baseX + perpX},${baseY + perpY} ${baseX - perpX},${baseY - perpY}`
}

function isNodeAffected(node: ComplianceNode): boolean {
  if (!analysis.value) return false
  return analysis.value.affectedNodes.some(n => n.app === node.app && n.entity === node.entity)
}

function isNodeTrigger(node: ComplianceNode): boolean {
  if (!analysis.value) return false
  return node.app === analysis.value.triggerApp
}

function isEdgeHighlighted(edge: ComplianceEdge): boolean {
  if (!analysis.value) return true
  const affected = analysis.value.affectedNodes
  const trigger = analysis.value.triggerApp
  // Highlight if source is trigger or affected, and target is affected
  const sourceMatch = edge.source.app === trigger || affected.some(n => n.app === edge.source.app && n.entity === edge.source.entity)
  const targetMatch = affected.some(n => n.app === edge.target.app && n.entity === edge.target.entity)
  return sourceMatch && targetMatch
}

function formatTime(dateStr: string): string {
  const d = new Date(dateStr)
  return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

async function fetchGraph() {
  loading.value = true
  error.value = null
  try {
    const data = await $fetch<GraphResponse>('/api/admin/compliance-graph')
    graphNodes.value = data.nodes
    graphEdges.value = data.edges
    history.value = data.history
    buildPositions(data.nodes)
  } catch (e: any) {
    error.value = e.data?.message || e.message || 'Failed to fetch compliance graph'
  } finally {
    loading.value = false
  }
}

async function runAnalysis() {
  analyzing.value = true
  error.value = null
  try {
    const result = await $fetch<ImpactAnalysis>('/api/admin/compliance-graph/impact', {
      method: 'POST',
      body: {
        triggerApp: triggerApp.value,
        triggerAction: triggerAction.value,
        entityType: entityType.value,
        entityId: entityId.value || undefined,
      },
    })
    analysis.value = result
    // Refresh history
    await fetchGraph()
  } catch (e: any) {
    error.value = e.data?.message || e.message || 'Impact analysis failed'
  } finally {
    analyzing.value = false
  }
}

function replayAnalysis(entry: ImpactAnalysis) {
  analysis.value = entry
  triggerApp.value = entry.triggerApp
  triggerAction.value = entry.triggerAction
  entityType.value = entry.affectedNodes[0]?.entity || ''
}

// Initial load
onMounted(() => {
  fetchGraph()
})
</script>
