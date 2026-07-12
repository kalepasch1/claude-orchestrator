<template>
  <div class="p-6">
    <div class="mb-6">
      <h2 class="text-xl font-semibold">Fleet API Gateway</h2>
      <p class="text-sm text-gray-400 mt-1">Centralized entry point for all cross-app API calls with rate limiting, circuit breaking, and request tracing.</p>
    </div>

    <!-- Stats Grid -->
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
      <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
        <div class="text-xs text-gray-500 uppercase tracking-wider mb-1">Total Requests</div>
        <div class="text-2xl font-bold text-gray-200">{{ stats?.totalRequests ?? 0 }}</div>
        <div class="text-xs text-gray-400 mt-1">
          <span class="text-green-400">{{ successRate }}%</span> success rate
        </div>
      </div>
      <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
        <div class="text-xs text-gray-500 uppercase tracking-wider mb-1">Avg Latency</div>
        <div class="text-2xl font-bold text-gray-200">{{ stats?.avgLatencyMs ?? 0 }}<span class="text-sm text-gray-500 ml-1">ms</span></div>
      </div>
      <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
        <div class="text-xs text-gray-500 uppercase tracking-wider mb-1">Cache Hit Rate</div>
        <div class="text-2xl font-bold text-gray-200">{{ cacheHitRate }}<span class="text-sm text-gray-500 ml-1">%</span></div>
      </div>
      <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
        <div class="text-xs text-gray-500 uppercase tracking-wider mb-1">Rate Limit Hits</div>
        <div class="text-2xl font-bold" :class="(stats?.rateLimitHits ?? 0) > 0 ? 'text-yellow-400' : 'text-gray-200'">
          {{ stats?.rateLimitHits ?? 0 }}
        </div>
      </div>
    </div>

    <!-- Health Overview -->
    <div class="bg-gray-900 border border-gray-800 rounded-lg p-4 mb-6">
      <h3 class="text-sm font-medium text-gray-300 mb-3">Health Overview</h3>
      <div class="flex flex-wrap gap-3">
        <div
          v-for="cs in stats?.circuitStates ?? []"
          :key="cs.app"
          class="flex items-center gap-2 bg-gray-800/50 rounded px-3 py-2"
        >
          <span
            class="w-2.5 h-2.5 rounded-full"
            :class="{
              'bg-green-500': cs.state === 'closed',
              'bg-yellow-500': cs.state === 'half-open',
              'bg-red-500 animate-pulse': cs.state === 'open',
            }"
          />
          <span class="text-sm text-gray-300">{{ cs.app }}</span>
          <span v-if="cs.failures > 0" class="text-xs text-red-400">{{ cs.failures }} failures</span>
        </div>
        <div v-if="!stats?.circuitStates?.length" class="text-sm text-gray-500">No circuit data available</div>
      </div>
    </div>

    <!-- Circuit Breaker Panel -->
    <div class="bg-gray-900 border border-gray-800 rounded-lg p-4 mb-6">
      <h3 class="text-sm font-medium text-gray-300 mb-3">Circuit Breakers</h3>
      <div class="overflow-x-auto">
        <table class="w-full">
          <thead>
            <tr class="border-b border-gray-800">
              <th class="text-left text-xs text-gray-500 uppercase tracking-wider pb-2 pr-4">App</th>
              <th class="text-left text-xs text-gray-500 uppercase tracking-wider pb-2 pr-4">State</th>
              <th class="text-left text-xs text-gray-500 uppercase tracking-wider pb-2 pr-4">Failures</th>
              <th class="text-left text-xs text-gray-500 uppercase tracking-wider pb-2 pr-4">Last Failure</th>
              <th class="text-left text-xs text-gray-500 uppercase tracking-wider pb-2 pr-4">Last Success</th>
              <th class="text-left text-xs text-gray-500 uppercase tracking-wider pb-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="cs in circuits"
              :key="cs.app"
              class="border-b border-gray-800/50"
            >
              <td class="py-2 pr-4 text-sm text-gray-300">{{ cs.app }}</td>
              <td class="py-2 pr-4">
                <span
                  class="text-xs px-2 py-0.5 rounded font-medium"
                  :class="circuitStateClass(cs.state)"
                >
                  {{ cs.state }}
                </span>
              </td>
              <td class="py-2 pr-4 text-sm text-gray-400">{{ cs.failures }}</td>
              <td class="py-2 pr-4 text-sm text-gray-400">{{ cs.lastFailure ? formatTime(cs.lastFailure) : '--' }}</td>
              <td class="py-2 pr-4 text-sm text-gray-400">{{ cs.lastSuccess ? formatTime(cs.lastSuccess) : '--' }}</td>
              <td class="py-2">
                <button
                  v-if="cs.state !== 'closed'"
                  class="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 disabled:bg-gray-800 disabled:text-gray-600 text-sm font-medium rounded transition-colors"
                  :disabled="resetting === cs.app"
                  @click="resetCircuit(cs.app)"
                >
                  {{ resetting === cs.app ? 'Resetting...' : 'Reset' }}
                </button>
              </td>
            </tr>
            <tr v-if="!circuits.length">
              <td colspan="6" class="py-4 text-sm text-gray-500 text-center">No circuit data available</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Rate Limit Meters -->
    <div class="bg-gray-900 border border-gray-800 rounded-lg p-4 mb-6">
      <h3 class="text-sm font-medium text-gray-300 mb-3">Requests by App</h3>
      <div class="space-y-3">
        <div v-for="[app, count] in sortedRequestsByApp" :key="app">
          <div class="flex items-center justify-between mb-1">
            <span class="text-sm text-gray-300">{{ app }}</span>
            <span class="text-sm text-gray-400">{{ count }}</span>
          </div>
          <div class="w-full bg-gray-800 rounded-full h-2">
            <div
              class="bg-indigo-600 h-2 rounded-full transition-all duration-500"
              :style="{ width: `${maxRequestCount > 0 ? (count / maxRequestCount) * 100 : 0}%` }"
            />
          </div>
        </div>
        <div v-if="!sortedRequestsByApp.length" class="text-sm text-gray-500">No request data available</div>
      </div>
    </div>

    <!-- Request Log -->
    <div class="bg-gray-900 border border-gray-800 rounded-lg p-4 mb-6">
      <h3 class="text-sm font-medium text-gray-300 mb-3">Recent Requests</h3>
      <div class="overflow-x-auto max-h-96 overflow-y-auto">
        <table class="w-full">
          <thead class="sticky top-0 bg-gray-900">
            <tr class="border-b border-gray-800">
              <th class="text-left text-xs text-gray-500 uppercase tracking-wider pb-2 pr-4">Trace ID</th>
              <th class="text-left text-xs text-gray-500 uppercase tracking-wider pb-2 pr-4">App</th>
              <th class="text-left text-xs text-gray-500 uppercase tracking-wider pb-2 pr-4">Method</th>
              <th class="text-left text-xs text-gray-500 uppercase tracking-wider pb-2 pr-4">Path</th>
              <th class="text-left text-xs text-gray-500 uppercase tracking-wider pb-2 pr-4">Caller</th>
              <th class="text-left text-xs text-gray-500 uppercase tracking-wider pb-2 pr-4">Time</th>
              <th class="text-left text-xs text-gray-500 uppercase tracking-wider pb-2">Cached</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="req in stats?.recentRequests ?? []"
              :key="req.traceId"
              class="border-b border-gray-800/50 hover:bg-gray-800/30 cursor-pointer"
              @click="viewTrace(req.traceId)"
            >
              <td class="py-2 pr-4 text-sm text-indigo-400 font-mono" :title="req.traceId">
                {{ req.traceId.slice(0, 8) }}
              </td>
              <td class="py-2 pr-4 text-sm text-gray-300">{{ req.app }}</td>
              <td class="py-2 pr-4">
                <span class="text-xs px-2 py-0.5 rounded font-medium" :class="methodClass(req.method)">
                  {{ req.method }}
                </span>
              </td>
              <td class="py-2 pr-4 text-sm text-gray-400 font-mono">{{ req.path }}</td>
              <td class="py-2 pr-4 text-sm text-gray-400">{{ req.caller }}</td>
              <td class="py-2 pr-4 text-sm text-gray-400">{{ formatTime(req.timestamp) }}</td>
              <td class="py-2 text-sm">
                <span v-if="req.cached" class="text-green-400">yes</span>
                <span v-else class="text-gray-500">no</span>
              </td>
            </tr>
            <tr v-if="!stats?.recentRequests?.length">
              <td colspan="7" class="py-4 text-sm text-gray-500 text-center">No recent requests</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Trace Detail Modal -->
    <div
      v-if="selectedTrace"
      class="fixed inset-0 bg-black/60 flex items-center justify-center z-50"
      @click.self="selectedTrace = null"
    >
      <div class="bg-gray-900 border border-gray-800 rounded-lg p-6 max-w-2xl w-full mx-4 max-h-[80vh] overflow-y-auto">
        <div class="flex items-center justify-between mb-4">
          <h3 class="text-sm font-medium text-gray-300">Trace Detail</h3>
          <button
            class="text-gray-400 hover:text-gray-200 transition-colors"
            @click="selectedTrace = null"
          >
            &times;
          </button>
        </div>
        <div v-if="traceLoading" class="text-sm text-gray-400">Loading trace...</div>
        <div v-else-if="traceData">
          <div class="space-y-3">
            <div>
              <div class="text-xs text-gray-500 uppercase tracking-wider mb-1">Trace ID</div>
              <div class="text-sm text-gray-300 font-mono">{{ traceData.traceId }}</div>
            </div>
            <div class="grid grid-cols-2 gap-3">
              <div>
                <div class="text-xs text-gray-500 uppercase tracking-wider mb-1">App</div>
                <div class="text-sm text-gray-300">{{ traceData.app }}</div>
              </div>
              <div>
                <div class="text-xs text-gray-500 uppercase tracking-wider mb-1">Status</div>
                <div class="text-sm font-medium" :class="traceData.status >= 400 ? 'text-red-400' : 'text-green-400'">
                  {{ traceData.status }}
                </div>
              </div>
              <div>
                <div class="text-xs text-gray-500 uppercase tracking-wider mb-1">Latency</div>
                <div class="text-sm text-gray-300">{{ traceData.latencyMs }}ms</div>
              </div>
              <div>
                <div class="text-xs text-gray-500 uppercase tracking-wider mb-1">From Cache</div>
                <div class="text-sm" :class="traceData.fromCache ? 'text-green-400' : 'text-gray-400'">
                  {{ traceData.fromCache ? 'Yes' : 'No' }}
                </div>
              </div>
              <div>
                <div class="text-xs text-gray-500 uppercase tracking-wider mb-1">Retry Count</div>
                <div class="text-sm text-gray-300">{{ traceData.retryCount }}</div>
              </div>
              <div>
                <div class="text-xs text-gray-500 uppercase tracking-wider mb-1">Circuit State</div>
                <span class="text-xs px-2 py-0.5 rounded font-medium" :class="circuitStateClass(traceData.circuitState)">
                  {{ traceData.circuitState }}
                </span>
              </div>
            </div>
            <div>
              <div class="text-xs text-gray-500 uppercase tracking-wider mb-1">Response Body</div>
              <pre class="bg-gray-800 border border-gray-700 rounded p-3 text-xs text-gray-300 overflow-x-auto max-h-60 overflow-y-auto">{{ formatJson(traceData.body) }}</pre>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Test Panel -->
    <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
      <h3 class="text-sm font-medium text-gray-300 mb-3">Test Gateway Route</h3>
      <div class="space-y-3">
        <div class="flex flex-wrap gap-3">
          <select
            v-model="testForm.app"
            class="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-indigo-500"
          >
            <option value="">Select app...</option>
            <option v-for="app in knownApps" :key="app" :value="app">{{ app }}</option>
          </select>
          <select
            v-model="testForm.method"
            class="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-indigo-500"
          >
            <option v-for="m in methods" :key="m" :value="m">{{ m }}</option>
          </select>
          <input
            v-model="testForm.path"
            type="text"
            placeholder="/api/health"
            class="flex-1 min-w-[200px] bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-indigo-500"
          />
        </div>
        <div class="flex flex-wrap gap-3">
          <textarea
            v-if="testForm.method === 'POST' || testForm.method === 'PUT'"
            v-model="testForm.body"
            placeholder='{"key": "value"}'
            rows="3"
            class="flex-1 min-w-[200px] bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-indigo-500 font-mono"
          />
          <input
            v-model="testForm.caller"
            type="text"
            placeholder="Caller (optional)"
            class="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-indigo-500"
          />
        </div>
        <div class="flex items-center gap-3">
          <button
            class="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 disabled:bg-gray-800 disabled:text-gray-600 text-sm font-medium rounded transition-colors"
            :disabled="!testForm.app || !testForm.path || routing"
            @click="routeRequest"
          >
            {{ routing ? 'Routing...' : 'Route Request' }}
          </button>
        </div>

        <!-- Test Response -->
        <div v-if="testResponse" class="bg-gray-800 border border-gray-700 rounded-lg p-4 mt-3">
          <div class="flex items-center gap-4 mb-3">
            <div>
              <span class="text-xs text-gray-500 mr-1">Status:</span>
              <span
                class="text-sm font-bold"
                :class="testResponse.status >= 400 ? 'text-red-400' : testResponse.status >= 300 ? 'text-yellow-400' : 'text-green-400'"
              >
                {{ testResponse.status }}
              </span>
            </div>
            <div>
              <span class="text-xs text-gray-500 mr-1">Latency:</span>
              <span class="text-sm text-gray-300">{{ testResponse.latencyMs }}ms</span>
            </div>
            <div>
              <span class="text-xs text-gray-500 mr-1">Cached:</span>
              <span class="text-sm" :class="testResponse.fromCache ? 'text-green-400' : 'text-gray-400'">
                {{ testResponse.fromCache ? 'yes' : 'no' }}
              </span>
            </div>
            <div>
              <span class="text-xs text-gray-500 mr-1">Trace:</span>
              <span
                class="text-sm text-indigo-400 font-mono cursor-pointer hover:text-indigo-300"
                :title="testResponse.traceId"
                @click="viewTrace(testResponse.traceId)"
              >
                {{ testResponse.traceId.slice(0, 8) }}
              </span>
            </div>
          </div>
          <pre class="text-xs text-gray-300 overflow-x-auto max-h-60 overflow-y-auto">{{ formatJson(testResponse.body) }}</pre>
        </div>
        <div v-if="testError" class="bg-red-900/20 border border-red-800 rounded-lg p-3 mt-3">
          <p class="text-sm text-red-400">{{ testError }}</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
definePageMeta({ layout: 'admin' })

interface CircuitState {
  app: string
  state: 'closed' | 'open' | 'half-open'
  failures: number
  lastFailure?: string
  lastSuccess?: string
  openedAt?: string
}

interface GatewayRequest {
  traceId: string
  app: string
  method: string
  path: string
  body?: any
  headers?: Record<string, string>
  caller: string
  timestamp: string
  cached: boolean
}

interface GatewayStats {
  totalRequests: number
  successCount: number
  failureCount: number
  cacheHits: number
  cacheMisses: number
  avgLatencyMs: number
  circuitStates: CircuitState[]
  rateLimitHits: number
  requestsByApp: Record<string, number>
  requestsByCaller: Record<string, number>
  recentRequests: GatewayRequest[]
}

interface GatewayResponse {
  traceId: string
  app: string
  status: number
  body: any
  latencyMs: number
  fromCache: boolean
  retryCount: number
  circuitState: string
}

const knownApps = ['apparently', 'tomorrow', 'smarter', 'galop', 'hisanta', 'pareto', 'orchestrator']
const methods = ['GET', 'POST', 'PUT', 'DELETE']

const { data: stats, refresh } = useFetch<GatewayStats>('/api/admin/gateway')

const circuits = ref<CircuitState[]>([])
const resetting = ref<string | null>(null)
const selectedTrace = ref<string | null>(null)
const traceData = ref<GatewayResponse | null>(null)
const traceLoading = ref(false)
const routing = ref(false)
const testResponse = ref<GatewayResponse | null>(null)
const testError = ref<string | null>(null)

const testForm = reactive({
  app: '',
  method: 'GET',
  path: '',
  body: '',
  caller: '',
})

// Computed
const successRate = computed(() => {
  if (!stats.value || stats.value.totalRequests === 0) return '0'
  return ((stats.value.successCount / stats.value.totalRequests) * 100).toFixed(1)
})

const cacheHitRate = computed(() => {
  if (!stats.value) return '0'
  const total = stats.value.cacheHits + stats.value.cacheMisses
  if (total === 0) return '0'
  return ((stats.value.cacheHits / total) * 100).toFixed(1)
})

const sortedRequestsByApp = computed<[string, number][]>(() => {
  if (!stats.value?.requestsByApp) return []
  return Object.entries(stats.value.requestsByApp).sort((a, b) => b[1] - a[1])
})

const maxRequestCount = computed(() => {
  if (!sortedRequestsByApp.value.length) return 0
  return sortedRequestsByApp.value[0][1]
})

// Methods
function circuitStateClass(state: string) {
  switch (state) {
    case 'closed': return 'bg-green-900/50 text-green-300'
    case 'half-open': return 'bg-yellow-900/50 text-yellow-300'
    case 'open': return 'bg-red-900/50 text-red-300'
    default: return 'bg-gray-800 text-gray-400'
  }
}

function methodClass(method: string) {
  switch (method) {
    case 'GET': return 'bg-blue-900/50 text-blue-300'
    case 'POST': return 'bg-green-900/50 text-green-300'
    case 'PUT': return 'bg-yellow-900/50 text-yellow-300'
    case 'DELETE': return 'bg-red-900/50 text-red-300'
    default: return 'bg-gray-800 text-gray-400'
  }
}

function formatTime(ts: string) {
  try {
    return new Date(ts).toLocaleTimeString()
  } catch {
    return ts
  }
}

function formatJson(data: any) {
  try {
    return typeof data === 'string' ? data : JSON.stringify(data, null, 2)
  } catch {
    return String(data)
  }
}

async function fetchCircuits() {
  try {
    const res = await $fetch<{ circuits: CircuitState[] }>('/api/admin/gateway/circuits')
    circuits.value = res.circuits
  } catch {
    // fail-soft
  }
}

async function resetCircuit(app: string) {
  resetting.value = app
  try {
    await $fetch('/api/admin/gateway/circuits/reset', {
      method: 'POST',
      body: { app },
    })
    await fetchCircuits()
    await refresh()
  } catch {
    // fail-soft
  } finally {
    resetting.value = null
  }
}

async function viewTrace(traceId: string) {
  selectedTrace.value = traceId
  traceLoading.value = true
  traceData.value = null
  try {
    const res = await $fetch<GatewayResponse>(`/api/admin/gateway/trace/${traceId}`)
    traceData.value = res
  } catch {
    traceData.value = null
  } finally {
    traceLoading.value = false
  }
}

async function routeRequest() {
  routing.value = true
  testResponse.value = null
  testError.value = null
  try {
    const payload: Record<string, any> = {
      app: testForm.app,
      method: testForm.method,
      path: testForm.path,
    }
    if ((testForm.method === 'POST' || testForm.method === 'PUT') && testForm.body) {
      try {
        payload.body = JSON.parse(testForm.body)
      } catch {
        payload.body = testForm.body
      }
    }
    if (testForm.caller) {
      payload.caller = testForm.caller
    }
    const res = await $fetch<GatewayResponse>('/api/admin/gateway/route', {
      method: 'POST',
      body: payload,
    })
    testResponse.value = res
    await refresh()
    await fetchCircuits()
  } catch (e: any) {
    testError.value = e?.data?.message || e?.message || 'Request failed'
  } finally {
    routing.value = false
  }
}

// Polling
let pollInterval: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  fetchCircuits()
  pollInterval = setInterval(() => {
    refresh()
    fetchCircuits()
  }, 10_000)
})

onUnmounted(() => {
  if (pollInterval) {
    clearInterval(pollInterval)
    pollInterval = null
  }
})
</script>
