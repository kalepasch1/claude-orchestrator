<script setup lang="ts">
definePageMeta({ layout: 'default' })
const supabase = useSupabaseClient<any>()
const user = useSupabaseUser()

const capabilities = ref<any[]>([])
const loops = ref<any[]>([])
const loading = ref(false)
const selectedCap = ref<string | null>(null)
const terminalPrompt = ref('')
const terminalLoading = ref(false)
const terminalOutput = ref('')
const projects = ref<any[]>([])
const activeTab = ref<'capabilities' | 'bots' | 'loops' | 'terminal'>('capabilities')

// CADE Bot Groups definition
const BOT_GROUPS = [
  { id: 1, name: 'Change Classification', bots: ['Change Type Analyzer', 'Impact Scope Assessor', 'Priority Calculator', 'Complexity Estimator'], status: 'active' },
  { id: 2, name: 'Placement Intelligence', bots: ['Layout Optimizer', 'Placement Predictor', 'Density Analyzer', 'Grid Harmonizer'], status: 'active' },
  { id: 3, name: 'Design Execution', bots: ['Style Implementer', 'Animation Controller', 'Typography Manager', 'Color System Bot'], status: 'active' },
  { id: 4, name: 'Quality Assurance', bots: ['Pixel Inspector', 'Consistency Checker', 'Regression Detector', 'A11y Validator'], status: 'active' },
  { id: 5, name: 'Analytics Engine', bots: ['Engagement Tracker', 'Heatmap Analyzer', 'Conversion Monitor', 'Session Recorder'], status: 'active' },
  { id: 6, name: 'Intelligence Layer', bots: ['Pattern Recognizer', 'Anomaly Detector', 'Trend Forecaster', 'Insight Generator'], status: 'active' },
  { id: 7, name: 'Brand Guardian', bots: ['Brand Consistency Bot', 'Asset Manager', 'Guidelines Enforcer', 'Cross-App Harmonizer'], status: 'active' },
  { id: 8, name: 'Simulation Engine', bots: ['User Flow Simulator', 'Load Tester', 'Stress Analyzer', 'Edge Case Generator'], status: 'active' },
  { id: 9, name: 'Cognitive Analysis', bots: ['Cognitive Load Sensor', 'Attention Flow Mapper', 'Decision Fatigue Monitor', 'Learning Curve Optimizer'], status: 'active' },
  { id: 10, name: 'Advanced Systems', bots: ['Cross-Platform Sync', 'Multi-Modal Adapter', 'Predictive UI Engine', 'Context Aware Bot'], status: 'active' },
  { id: 11, name: 'Autonomous Intelligence', bots: ['Temporal Design Intel', 'Competitive Radar', 'Design Debt Quantifier', 'Collaborative Memory'], status: 'active' },
  { id: 12, name: 'Self-Operating Design', bots: ['Zero-State Intel', 'Micro-Funnel Optimizer', 'Accessibility Generator', 'Sentiment Engine'], status: 'active' },
  { id: 13, name: 'Contextual Intelligence', bots: ['Context Mapper', 'Intent Predictor', 'Behavior Modeler', 'Situation Analyzer'], status: 'active' },
  { id: 14, name: 'Adaptive Content', bots: ['Content Personalizer', 'Dynamic Copy Engine', 'Tone Adjuster', 'Reading Level Adapter'], status: 'active' },
  { id: 15, name: 'Behavioral Conditioning', bots: ['Reward System Bot', 'Streak Manager', 'Celebration Engine', 'Progress Tracker'], status: 'active' },
]

async function loadAll() {
  loading.value = true
  const [caps, lps, prj] = await Promise.all([
    supabase.from('capabilities').select('*').order('maturity', { ascending: false }),
    supabase.from('loops').select('*').order('project'),
    supabase.from('projects').select('*').order('name'),
  ])
  capabilities.value = caps.data || []
  loops.value = lps.data || []
  projects.value = prj.data || []
  loading.value = false
}

async function toggleLoop(loop: any) {
  await supabase.from('loops').update({ enabled: !loop.enabled }).eq('id', loop.id)
  loop.enabled = !loop.enabled
}

async function runTerminalCommand() {
  if (!terminalPrompt.value.trim()) return
  terminalLoading.value = true
  terminalOutput.value = ''
  try {
    const proj = projects.value[0]
    if (!proj) { terminalOutput.value = 'Error: No projects configured'; return }
    const slug = 'design-terminal-' + Date.now().toString(36)
    await supabase.from('tasks').insert({
      project_id: proj.id,
      slug,
      prompt: `DESIGN TERMINAL COMMAND:\n${terminalPrompt.value.trim()}`,
      kind: 'build',
      state: 'QUEUED',
      note: 'source:design-terminal',
    })
    terminalOutput.value = `Task queued: ${slug}\nThe orchestrator will process this command through the CADE pipeline.`
    terminalPrompt.value = ''
  } catch (e: any) {
    terminalOutput.value = 'Error: ' + (e.message || String(e))
  } finally {
    terminalLoading.value = false
  }
}

function maturityPct(m: any) { return Math.min(100, Math.max(0, Number(m || 0) * 100)) }
function statusColor(s: string) {
  if (s === 'trusted') return 'bg-blue-100 text-blue-700 border-blue-200'
  if (s === 'productizable') return 'bg-emerald-100 text-emerald-700 border-emerald-200'
  if (s === 'experimental') return 'bg-amber-100 text-amber-700 border-amber-200'
  return 'bg-gray-100 text-gray-600 border-gray-200'
}
function maturityColor(n: number) {
  if (n >= 80) return 'bg-emerald-500'
  if (n >= 50) return 'bg-blue-500'
  return 'bg-gray-300'
}
function healthColor(h: string) {
  if (h === 'healthy') return 'text-emerald-600'
  if (h === 'degraded') return 'text-amber-600'
  if (h === 'down') return 'text-red-600'
  return 'text-gray-500'
}

onMounted(() => { if (user.value) loadAll() })
watch(user, u => { if (u) loadAll() })
</script>

<template>
  <div class="min-h-screen bg-white text-gray-900">
    <div class="max-w-6xl mx-auto px-6 py-6 space-y-6">

      <!-- Header -->
      <div class="flex items-center justify-between">
        <div>
          <h1 class="text-xl font-bold text-gray-900" style="font-family: 'Fraunces', serif;">Orchestrators & Capabilities</h1>
          <p class="text-sm text-gray-500 mt-0.5">AI capability registry, CADE bot management, and design terminal</p>
        </div>
        <button @click="loadAll" class="px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-700 text-sm rounded-lg border border-gray-200 transition-colors">↻ Refresh</button>
      </div>

      <!-- Tab Navigation -->
      <div class="flex gap-1 bg-gray-100 rounded-lg p-1">
        <button v-for="tab in [
          { key: 'capabilities', label: 'Capabilities', count: capabilities.length },
          { key: 'bots', label: 'CADE Bots', count: BOT_GROUPS.length * 4 },
          { key: 'loops', label: 'Automation Loops', count: loops.length },
          { key: 'terminal', label: 'Design Terminal' },
        ]" :key="tab.key"
          @click="activeTab = tab.key as any"
          class="flex-1 px-4 py-2 text-sm rounded-md transition-colors"
          :class="activeTab === tab.key ? 'bg-white text-gray-900 font-medium shadow-sm' : 'text-gray-500 hover:text-gray-700'">
          {{ tab.label }}
          <span v-if="tab.count != null" class="ml-1 text-xs text-gray-400">({{ tab.count }})</span>
        </button>
      </div>

      <div v-if="loading" class="text-center py-12 text-gray-400">Loading...</div>

      <!-- Capabilities Tab -->
      <div v-else-if="activeTab === 'capabilities'" class="space-y-4">
        <div v-if="capabilities.length === 0" class="text-center py-12 text-gray-400">
          No capabilities found in registry. Run distill.py to extract capabilities from your apps.
        </div>
        <div v-else class="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div v-for="cap in capabilities" :key="cap.id"
            class="bg-white border rounded-xl overflow-hidden transition-shadow hover:shadow-md cursor-pointer"
            :class="selectedCap === cap.id ? 'border-blue-300 shadow-md ring-1 ring-blue-200' : 'border-gray-200'"
            @click="selectedCap = selectedCap === cap.id ? null : cap.id">

            <div class="p-4">
              <div class="flex items-start justify-between gap-3 mb-3">
                <div>
                  <h3 class="text-base font-semibold text-gray-900">{{ cap.name }}</h3>
                  <span v-if="cap.slug" class="text-xs font-mono text-gray-400">{{ cap.slug }}</span>
                </div>
                <span class="text-xs px-2.5 py-1 rounded-full border flex-shrink-0 font-medium" :class="statusColor(cap.status)">{{ cap.status }}</span>
              </div>

              <p v-if="cap.summary" class="text-sm text-gray-500 mb-3 leading-relaxed">{{ cap.summary }}</p>

              <div class="flex items-center gap-3">
                <div class="flex-1">
                  <div class="flex justify-between text-xs text-gray-500 mb-1">
                    <span>Maturity</span>
                    <span class="font-mono">{{ Math.round(maturityPct(cap.maturity)) }}%</span>
                  </div>
                  <div class="h-2 bg-gray-100 rounded-full overflow-hidden">
                    <div class="h-full rounded-full transition-all" :class="maturityColor(maturityPct(cap.maturity))" :style="`width: ${maturityPct(cap.maturity)}%`"></div>
                  </div>
                </div>
                <div class="flex items-center gap-2">
                  <span v-if="cap.domain" class="text-xs px-2 py-1 rounded-md bg-gray-100 text-gray-600">{{ cap.domain }}</span>
                  <span v-if="cap.regulated" class="text-xs px-2 py-1 rounded-md bg-red-50 text-red-600">regulated</span>
                </div>
              </div>
            </div>

            <!-- Expanded detail -->
            <div v-if="selectedCap === cap.id" class="border-t border-gray-100 bg-gray-50 p-4 space-y-3" @click.stop>
              <div class="grid grid-cols-2 gap-3 text-sm">
                <div>
                  <span class="text-xs text-gray-400 uppercase tracking-wide">Domain</span>
                  <p class="text-gray-700 font-medium">{{ cap.domain || 'General' }}</p>
                </div>
                <div>
                  <span class="text-xs text-gray-400 uppercase tracking-wide">Status</span>
                  <p class="text-gray-700 font-medium">{{ cap.status }}</p>
                </div>
                <div>
                  <span class="text-xs text-gray-400 uppercase tracking-wide">Created</span>
                  <p class="text-gray-700">{{ cap.created_at ? new Date(cap.created_at).toLocaleDateString() : '—' }}</p>
                </div>
                <div>
                  <span class="text-xs text-gray-400 uppercase tracking-wide">Maturity Score</span>
                  <p class="text-gray-700 font-mono">{{ cap.maturity || 0 }}</p>
                </div>
              </div>
              <div v-if="cap.description || cap.summary" class="text-sm text-gray-600 bg-white rounded-lg p-3 border border-gray-200">
                {{ cap.description || cap.summary }}
              </div>
              <div class="flex gap-2">
                <button class="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white text-xs rounded-lg transition-colors" @click.stop="terminalPrompt = `Analyze and improve capability: ${cap.name} (${cap.slug})`; activeTab = 'terminal'">
                  Open in Terminal
                </button>
                <button class="px-3 py-1.5 bg-gray-100 hover:bg-gray-200 text-gray-700 text-xs rounded-lg border border-gray-200 transition-colors">
                  View Logs
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- CADE Bots Tab -->
      <div v-else-if="activeTab === 'bots'" class="space-y-4">
        <p class="text-sm text-gray-500">{{ BOT_GROUPS.length }} groups, {{ BOT_GROUPS.length * 4 }} specialized AI bots managing design, quality, analytics, and autonomous intelligence.</p>
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          <div v-for="group in BOT_GROUPS" :key="group.id"
            class="bg-white border border-gray-200 rounded-xl p-4 hover:shadow-md transition-shadow">
            <div class="flex items-center justify-between mb-3">
              <div class="flex items-center gap-2">
                <span class="w-6 h-6 rounded-lg bg-blue-100 text-blue-700 flex items-center justify-center text-xs font-bold">{{ group.id }}</span>
                <h3 class="text-sm font-semibold text-gray-900">{{ group.name }}</h3>
              </div>
              <span class="w-2 h-2 rounded-full bg-emerald-500"></span>
            </div>
            <div class="space-y-1">
              <div v-for="bot in group.bots" :key="bot" class="flex items-center gap-2 text-xs text-gray-600 py-0.5">
                <span class="w-1 h-1 rounded-full bg-gray-300"></span>
                {{ bot }}
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Loops Tab -->
      <div v-else-if="activeTab === 'loops'" class="space-y-4">
        <div v-if="loops.length === 0" class="text-center py-12 text-gray-400">No loops configured</div>
        <div v-else class="bg-white border border-gray-200 rounded-xl overflow-hidden">
          <table class="w-full text-sm">
            <thead>
              <tr class="bg-gray-50 text-gray-500 text-xs uppercase tracking-wider">
                <th class="text-left px-4 py-3 font-medium">Project</th>
                <th class="text-left px-4 py-3 font-medium">Type</th>
                <th class="text-left px-4 py-3 font-medium">Cadence</th>
                <th class="text-left px-4 py-3 font-medium">Health</th>
                <th class="text-right px-4 py-3 font-medium">Status</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-gray-100">
              <tr v-for="l in loops" :key="l.id" class="hover:bg-gray-50">
                <td class="px-4 py-3 text-gray-900 font-medium">{{ l.project }}</td>
                <td class="px-4 py-3">
                  <span class="text-xs px-2 py-0.5 rounded-full font-medium"
                    :class="l.type === 'remediate' ? 'bg-red-50 text-red-700' : l.type === 'optimize' ? 'bg-blue-50 text-blue-700' : l.type === 'learn' ? 'bg-purple-50 text-purple-700' : 'bg-gray-100 text-gray-600'">
                    {{ l.type }}
                  </span>
                </td>
                <td class="px-4 py-3 text-gray-500 font-mono text-xs">{{ l.cadence_seconds ? `${l.cadence_seconds}s` : '—' }}</td>
                <td class="px-4 py-3 text-xs font-medium" :class="healthColor(l.health)">{{ l.health || '—' }}</td>
                <td class="px-4 py-3 text-right">
                  <button @click="toggleLoop(l)"
                    class="px-3 py-1 text-xs rounded-full border transition-colors"
                    :class="l.enabled ? 'border-emerald-300 text-emerald-700 bg-emerald-50 hover:bg-red-50 hover:text-red-700 hover:border-red-200' : 'border-gray-300 text-gray-500 hover:bg-emerald-50 hover:text-emerald-700 hover:border-emerald-200'">
                    {{ l.enabled ? 'enabled' : 'disabled' }}
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Design Terminal Tab -->
      <div v-else-if="activeTab === 'terminal'" class="space-y-4">
        <div class="bg-white border border-gray-200 rounded-xl overflow-hidden">
          <div class="px-5 py-3 border-b border-gray-200 flex items-center gap-3">
            <span class="text-emerald-600 text-xs font-bold">→</span>
            <span class="text-sm font-semibold text-gray-900" style="font-family: 'Fraunces', serif;">Design Terminal</span>
            <span class="text-xs text-gray-400">Send commands to the CADE orchestration pipeline</span>
          </div>
          <div class="p-5 space-y-4">
            <div class="bg-gray-900 rounded-lg p-4 min-h-[200px]" style="font-family: 'JetBrains Mono', monospace;">
              <div v-if="terminalOutput" class="text-sm text-emerald-400 whitespace-pre-wrap mb-4">{{ terminalOutput }}</div>
              <div v-else class="text-sm text-gray-500 mb-4">
                <div class="text-gray-400 mb-2">Welcome to the Design Terminal. Available commands:</div>
                <div class="text-gray-500">• Describe UI/UX improvements to implement</div>
                <div class="text-gray-500">• Run CADE analysis on specific components</div>
                <div class="text-gray-500">• Queue design tasks for autonomous execution</div>
                <div class="text-gray-500">• Configure conditioning cues for apps</div>
              </div>
              <div class="flex items-center gap-2">
                <span class="text-emerald-500">$</span>
                <input
                  v-model="terminalPrompt"
                  @keydown.enter="runTerminalCommand"
                  placeholder="Type a design command..."
                  class="flex-1 bg-transparent text-white text-sm outline-none placeholder-gray-600"
                />
              </div>
            </div>
            <div class="flex gap-3">
              <button @click="runTerminalCommand" :disabled="terminalLoading || !terminalPrompt.trim()"
                class="px-5 py-2 bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-40">
                {{ terminalLoading ? 'Executing...' : '→ Execute' }}
              </button>
              <button @click="terminalOutput = ''" class="px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-600 text-sm rounded-lg border border-gray-200 transition-colors">
                Clear
              </button>
            </div>

            <!-- Quick action buttons -->
            <div class="border-t border-gray-200 pt-4">
              <div class="text-xs text-gray-400 uppercase tracking-wider mb-2">Quick Actions</div>
              <div class="flex flex-wrap gap-2">
                <button v-for="cmd in [
                  'Run full CADE audit on all apps',
                  'Analyze cognitive load across portfolio',
                  'Generate A/B test recommendations',
                  'Audit conditioning cue effectiveness',
                  'Check brand consistency score',
                  'Review accessibility compliance',
                ]" :key="cmd"
                  @click="terminalPrompt = cmd"
                  class="px-3 py-1.5 text-xs bg-gray-50 hover:bg-gray-100 text-gray-600 rounded-lg border border-gray-200 transition-colors">
                  {{ cmd }}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

    </div>
  </div>
</template>
