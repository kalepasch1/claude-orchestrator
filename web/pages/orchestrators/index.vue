<script setup lang="ts">
definePageMeta({ layout: 'default' })

type CommandFile = { name: string; type: string; size: number; base64: string; text?: string }

const supabase = useSupabaseClient<any>()
const projects = ref<any[]>([])
const recentTasks = ref<any[]>([])
const prompt = ref('')
const projectId = ref('')
const attachments = ref<CommandFile[]>([])
const attachmentInput = ref<HTMLInputElement | null>(null)
const submitting = ref(false)
const listening = ref(false)
const notice = ref('')
const errorMessage = ref('')
const loadError = ref('')
const projectChoices = ref<any[]>([])
const lastRoute = ref<any>(null)

const commandCenters = [
  { slug: 'engineering-orchestrator', mark: '01', eyebrow: 'Build & ship', name: 'Engineering', summary: 'Illuminate code, coordinate specialist agents, repair defects, and release verified improvements.', actions: ['Build a feature', 'Repair production', 'Optimize an app'] },
  { slug: 'design-orchestrator', mark: '02', eyebrow: 'Create & refine', name: 'Design + Creative', summary: 'Turn product intent into interfaces, brand systems, motion, campaigns, and production assets.', actions: ['Design a product', 'Create motion', 'Evolve the brand'] },
  { slug: 'business-orchestrator', mark: '03', eyebrow: 'Operate the company', name: 'Business Operations', summary: 'Coordinate people, finance, knowledge, vendors, priorities, and execution across every company.', actions: ['Run the business', 'Manage a vendor', 'Plan the quarter'] },
  { slug: 'legal-orchestrator', mark: '04', eyebrow: 'Review & protect', name: 'Legal + Compliance', summary: 'Review agreements, draft evidence-backed work, manage entities, and continuously monitor obligations.', actions: ['Review a contract', 'Prepare a filing', 'Assess compliance'] },
  { slug: 'growth-orchestrator', mark: '05', eyebrow: 'Find & grow demand', name: 'Marketing + Growth', summary: 'Develop positioning, content, campaigns, experiments, and measurable programs that compound.', actions: ['Plan a launch', 'Create content', 'Improve conversion'] },
  { slug: 'research-orchestrator', mark: '06', eyebrow: 'Learn as a hive', name: 'Research + Hivemind', summary: 'Synthesize knowledge across companies, markets, conversations, and decisions without losing provenance.', actions: ['Research a market', 'Compare options', 'Write a decision brief'] },
]

const quickStarts = [
  'Review every active app, fix the highest-impact issue, and show me proof.',
  'Turn this idea into a scoped product plan and begin the first safe implementation.',
  'Summarize risks and priorities across my companies, then recommend today’s focus.',
  'Audit legal, compliance, marketing, and operational gaps across the portfolio.',
]

const systemSteps = [
  { step: '01', title: 'Understand', body: 'Projects, files, company knowledge, constraints, and prior decisions become one working context.' },
  { step: '02', title: 'Illuminate', body: 'The development optimization layer finds leverage, dependencies, risks, and the best execution route.' },
  { step: '03', title: 'Coordinate', body: 'Specialists work in parallel across engineering, design, research, legal, growth, and operations.' },
  { step: '04', title: 'Prove', body: 'Tests, evidence, accessibility, regressions, approvals, and release health close the loop.' },
]

const taskCounts = computed(() => ({
  running: recentTasks.value.filter(task => task.state === 'RUNNING').length,
  queued: recentTasks.value.filter(task => ['QUEUED', 'ASSIGNED', 'READY'].includes(task.state)).length,
  attention: recentTasks.value.filter(task => ['FAILED', 'BLOCKED', 'NEEDS_APPROVAL'].includes(task.state)).length,
}))

function stateClass(state: string) {
  if (['DONE', 'MERGED', 'DEPLOYED'].includes(state)) return 'done'
  if (state === 'RUNNING') return 'running'
  if (['FAILED', 'BLOCKED'].includes(state)) return 'failed'
  return 'queued'
}

function formatState(state: string) {
  return String(state || 'queued').replaceAll('_', ' ').toLowerCase()
}

function formatDate(value: string) {
  return new Intl.RelativeTimeFormat('en', { numeric: 'auto' }).format(
    -Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 3_600_000)),
    'hour',
  )
}

async function authedFetch<T = any>(url: string, options: any = {}) {
  const { data: { session } } = await supabase.auth.getSession()
  return $fetch<T>(url, {
    ...options,
    headers: { ...(options.headers || {}), ...(session?.access_token ? { authorization: `Bearer ${session.access_token}` } : {}) },
  })
}

async function load() {
  loadError.value = ''
  const [projectResult, taskResult] = await Promise.all([
    supabase.from('projects').select('id,name').order('name'),
    supabase.from('tasks').select('id,slug,state,kind,created_at').order('created_at', { ascending: false }).limit(8),
  ])
  projects.value = projectResult.data || []
  recentTasks.value = taskResult.data || []
  if (projectResult.error || taskResult.error) loadError.value = 'Live portfolio status is temporarily unavailable. You can still submit a command.'
}

async function addFiles(event: Event) {
  errorMessage.value = ''
  const input = event.target as HTMLInputElement
  const selected = Array.from(input.files || [])
  for (const file of selected) {
    if (attachments.value.length >= 5) {
      errorMessage.value = 'Add up to five files per command.'
      break
    }
    if (file.size > 8 * 1024 * 1024) {
      errorMessage.value = `${file.name} is larger than 8 MB.`
      continue
    }
    const base64 = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => resolve(String(reader.result || '').split(',')[1] || '')
      reader.onerror = reject
      reader.readAsDataURL(file)
    })
    const text = /^(text\/|application\/json)/.test(file.type) ? (await file.text()).slice(0, 50_000) : undefined
    attachments.value.push({ name: file.name, type: file.type || 'text/plain', size: file.size, base64, text })
  }
  input.value = ''
}

function startDictation() {
  const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
  if (!SpeechRecognition) {
    errorMessage.value = 'Voice dictation is not supported in this browser.'
    return
  }
  const recognition = new SpeechRecognition()
  recognition.continuous = false
  recognition.interimResults = false
  recognition.lang = 'en-US'
  listening.value = true
  recognition.onresult = (event: any) => {
    const words = String(event.results?.[0]?.[0]?.transcript || '').trim()
    prompt.value = [prompt.value.trim(), words].filter(Boolean).join(' ')
  }
  recognition.onerror = () => { errorMessage.value = 'Dictation could not start. Check microphone access and try again.' }
  recognition.onend = () => { listening.value = false }
  recognition.start()
}

async function submit(chosenProject?: string) {
  if (!prompt.value.trim() && !attachments.value.length) return
  submitting.value = true
  notice.value = ''
  errorMessage.value = ''
  projectChoices.value = []
  lastRoute.value = null
  try {
    let context: any = null
    if (attachments.value.length) {
      context = await authedFetch('/api/command/context', {
        method: 'POST',
        body: { command: prompt.value.trim(), files: attachments.value },
      })
    }
    const baseIntent = prompt.value.trim() || 'Review the attached context, determine the best next action, and execute it safely.'
    const intent = context?.reference ? `${baseIntent}\n\nContext reference: ${context.reference}` : baseIntent
    const result = await authedFetch<any>('/api/tasks/intake', {
      method: 'POST',
      body: { intent, project_id: chosenProject || projectId.value || undefined, source: 'command-center' },
    })
    lastRoute.value = result
    notice.value = `Command accepted. Madeus routed it to ${result.project?.name || 'the right workspace'}.`
    prompt.value = ''
    attachments.value = []
    await load()
  } catch (error: any) {
    if (error?.statusCode === 409 || error?.data?.code === 'project_required') {
      projectChoices.value = error?.data?.projects || projects.value
      notice.value = 'Choose the workspace this command should change.'
    } else {
      errorMessage.value = error?.data?.message || error?.message || 'Madeus could not route this command. Your brief is still here—try again.'
    }
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  await load()
  try {
    const pending = JSON.parse(sessionStorage.getItem('madeus:pending-command') || 'null')
    if (pending?.intent && Date.now() - Number(pending.created_at || 0) < 86_400_000) prompt.value = String(pending.intent)
    if (pending) sessionStorage.removeItem('madeus:pending-command')
  } catch {
    sessionStorage.removeItem('madeus:pending-command')
  }
})
</script>

<template>
  <main class="command-page">
    <section class="command-hero">
      <div class="hero-copy">
        <div class="eyebrow"><span class="live-dot" /> Primary command center</div>
        <h1>Run the work.<br><span>Not the workflow.</span></h1>
        <p>Brief Madeus once. It connects your portfolio’s knowledge, illuminates the best path, coordinates specialist work, and returns proof—not a pile of chat threads.</p>
      </div>

      <form class="command-composer" @submit.prevent="submit()">
        <div class="composer-topline">
          <span>What outcome do you want?</span>
          <span class="autopilot-pill"><i /> Autopilot ready</span>
        </div>
        <textarea v-model="prompt" rows="5" aria-label="Command" placeholder="Build, investigate, review, operate, or improve anything across your companies…" />

        <div v-if="attachments.length" class="attachment-list">
          <button v-for="(file, index) in attachments" :key="`${file.name}-${index}`" type="button" @click="attachments.splice(index, 1)">
            <span>▰</span> {{ file.name }} <b>×</b>
          </button>
        </div>

        <div class="composer-tools">
          <div class="input-tools">
            <input ref="attachmentInput" class="sr-only" type="file" multiple accept="image/png,image/jpeg,image/webp,image/gif,application/pdf,application/json,text/plain,text/csv,text/markdown,audio/webm,audio/mpeg,audio/mp4,video/mp4,video/webm" @change="addFiles">
            <button type="button" class="tool-button" @click="attachmentInput?.click()"><span>＋</span> Add context</button>
            <button type="button" class="tool-button" :class="{ active: listening }" @click="startDictation"><span>{{ listening ? '◉' : '●' }}</span> {{ listening ? 'Listening…' : 'Dictate' }}</button>
            <label class="project-picker">
              <span>Workspace</span>
              <select v-model="projectId" aria-label="Workspace">
                <option value="">Auto-detect</option>
                <option v-for="project in projects" :key="project.id" :value="project.id">{{ project.name }}</option>
              </select>
            </label>
          </div>
          <button class="send-button" :disabled="submitting || (!prompt.trim() && !attachments.length)">
            {{ submitting ? 'Routing…' : 'Start work' }} <span>↗</span>
          </button>
        </div>

        <div class="quick-starts" aria-label="Quick starts">
          <button v-for="item in quickStarts" :key="item" type="button" @click="prompt = item">{{ item }}</button>
        </div>

        <div class="feedback" aria-live="polite">
          <p v-if="notice" class="notice">{{ notice }}</p>
          <p v-if="errorMessage" class="error">{{ errorMessage }}</p>
          <div v-if="projectChoices.length" class="project-choices">
            <button v-for="project in projectChoices" :key="project.id" type="button" @click="projectId = project.id; submit(project.id)">{{ project.name }}</button>
          </div>
          <div v-if="lastRoute" class="route-receipt">
            <span>Route created</span><b>{{ lastRoute.task?.slug }}</b><NuxtLink to="/queue">Open execution queue →</NuxtLink>
          </div>
        </div>
      </form>
    </section>

    <section class="status-strip" aria-label="Portfolio execution status">
      <div><span>Command fabric</span><b><i class="live-dot" /> Ready</b></div>
      <div><span>Running now</span><b>{{ taskCounts.running }}</b></div>
      <div><span>Queued</span><b>{{ taskCounts.queued }}</b></div>
      <div><span>Needs attention</span><b>{{ taskCounts.attention }}</b></div>
      <NuxtLink to="/queue">View the full queue <span>↗</span></NuxtLink>
    </section>

    <section class="operating-system">
      <div class="section-intro">
        <div><span class="section-number">01 / Operating system</span><h2>One intelligence layer.<br>Every company function.</h2></div>
        <p>Madeus replaces fragmented AI sessions with a durable system that understands your businesses, remembers how they work, and can act across them.</p>
      </div>
      <div class="system-flow">
        <article v-for="item in systemSteps" :key="item.step">
          <span>{{ item.step }}</span><div class="flow-signal"><i /></div><h3>{{ item.title }}</h3><p>{{ item.body }}</p>
        </article>
      </div>
    </section>

    <section class="workspace-section">
      <div class="section-intro compact">
        <div><span class="section-number">02 / Specialist workspaces</span><h2>Direct any part of the business.</h2></div>
        <p>Open a focused control surface when you need deeper tools, evidence, previews, or approvals.</p>
      </div>
      <div class="center-grid">
        <NuxtLink v-for="center in commandCenters" :key="center.slug" :to="`/orchestrators/${center.slug}`" class="center-card">
          <div class="card-top"><span>{{ center.mark }}</span><i>↗</i></div>
          <small>{{ center.eyebrow }}</small><h3>{{ center.name }}</h3><p>{{ center.summary }}</p>
          <div class="action-tags"><span v-for="action in center.actions" :key="action">{{ action }}</span></div>
        </NuxtLink>
      </div>
    </section>

    <section class="activity-section">
      <div class="section-intro compact">
        <div><span class="section-number">03 / Live execution</span><h2>Know what is moving.</h2></div>
        <NuxtLink to="/sign-offs">Review signoffs →</NuxtLink>
      </div>
      <p v-if="loadError" class="load-error">{{ loadError }}</p>
      <div v-if="recentTasks.length" class="activity-list">
        <NuxtLink v-for="task in recentTasks" :key="task.id" to="/queue" class="activity-row">
          <span class="state-dot" :class="stateClass(task.state)" />
          <div><b>{{ task.slug }}</b><span>{{ task.kind || 'work' }} · {{ formatDate(task.created_at) }}</span></div>
          <em :class="stateClass(task.state)">{{ formatState(task.state) }}</em><i>↗</i>
        </NuxtLink>
      </div>
      <div v-else class="empty-state"><span>◎</span><div><b>Your execution stream starts here.</b><p>Give Madeus an outcome above and its route, evidence, and status will appear here.</p></div></div>
    </section>
  </main>
</template>

<style scoped>
.command-page{--ink:#071c35;--muted:#52647a;--blue:#0758ee;--line:#dce5ef;max-width:1440px;margin:0 auto;padding:26px 34px 90px;color:var(--ink)}
.command-hero{position:relative;display:grid;grid-template-columns:minmax(300px,.8fr) minmax(560px,1.25fr);gap:68px;align-items:center;min-height:610px;padding:60px 4%;overflow:hidden;border:1px solid #d6e3f4;border-radius:28px;background:radial-gradient(circle at 7% 5%,rgba(55,133,255,.2),transparent 34%),linear-gradient(145deg,#f9fcff 0%,#eff6ff 52%,#f9fbfd 100%);box-shadow:0 28px 80px rgba(8,52,111,.12)}
.command-hero:after{content:"";position:absolute;right:-100px;top:-160px;width:520px;height:520px;border:1px solid rgba(7,88,238,.15);border-radius:50%;box-shadow:0 0 0 70px rgba(7,88,238,.035),0 0 0 140px rgba(7,88,238,.025);pointer-events:none}
.hero-copy,.command-composer{position:relative;z-index:1}.eyebrow,.section-number{display:flex;align-items:center;gap:9px;color:#255479;font-size:11px;font-weight:800;letter-spacing:.14em;text-transform:uppercase}.live-dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#21bb78;box-shadow:0 0 0 5px rgba(33,187,120,.13)}
h1{margin:26px 0 22px;font-size:clamp(48px,5.2vw,78px);line-height:.94;letter-spacing:-.065em}h1 span{color:var(--blue)}.hero-copy>p{max-width:570px;margin:0;color:#405970;font-size:18px;line-height:1.65}
.command-composer{padding:25px;border:1px solid rgba(149,176,211,.72);border-radius:22px;background:rgba(255,255,255,.9);box-shadow:0 24px 65px rgba(10,50,105,.16);backdrop-filter:blur(18px)}.composer-topline{display:flex;justify-content:space-between;align-items:center;margin-bottom:13px;font-size:12px;font-weight:800;letter-spacing:.04em}.autopilot-pill{display:flex;align-items:center;gap:7px;padding:7px 10px;border-radius:999px;color:#0c734e;background:#e5f8ef;font-size:10px;text-transform:uppercase}.autopilot-pill i{width:6px;height:6px;border-radius:50%;background:#20b978}.command-composer textarea{width:100%;min-height:145px;padding:5px 2px 18px;border:0;resize:vertical;background:transparent;color:var(--ink);font:600 20px/1.55 inherit;outline:0}.command-composer textarea::placeholder{color:#8292a6}.composer-tools{display:flex;justify-content:space-between;gap:16px;padding-top:15px;border-top:1px solid var(--line)}.input-tools{display:flex;align-items:center;gap:7px;flex-wrap:wrap}.tool-button,.project-picker{display:flex;align-items:center;gap:7px;height:38px;padding:0 11px;border:1px solid #d8e2ee;border-radius:9px;background:#fff;color:#425b74;font:700 11px inherit}.tool-button{cursor:pointer}.tool-button:hover,.tool-button.active{border-color:#88aff8;color:var(--blue);background:#f2f7ff}.project-picker span{display:none}.project-picker select{max-width:145px;border:0;background:transparent;color:inherit;font:inherit;outline:0}.send-button{min-width:132px;border:0;border-radius:10px;background:var(--blue);color:#fff;font:800 13px inherit;box-shadow:0 9px 22px rgba(7,88,238,.25);cursor:pointer}.send-button:disabled{opacity:.45;cursor:not-allowed}.attachment-list,.quick-starts,.project-choices{display:flex;gap:7px;flex-wrap:wrap}.attachment-list{margin:0 0 12px}.attachment-list button,.project-choices button{padding:7px 10px;border:1px solid #cbdcf1;border-radius:8px;background:#f4f8ff;color:#28527f;font:700 11px inherit;cursor:pointer}.attachment-list b{margin-left:5px}.quick-starts{margin-top:16px}.quick-starts button{max-width:47%;padding:0;border:0;background:transparent;color:#718398;font:600 11px/1.35 inherit;text-align:left;cursor:pointer}.quick-starts button:hover{color:var(--blue)}.feedback{font-size:12px}.notice,.error,.load-error{margin:14px 0 0;padding:10px 12px;border-radius:8px}.notice{color:#126646;background:#eaf9f1}.error,.load-error{color:#a33a3a;background:#fff0f0}.route-receipt{display:flex;align-items:center;gap:13px;margin-top:13px;padding:11px 13px;border:1px solid #bfe5d2;border-radius:10px;background:#f3fcf7}.route-receipt span{color:#438268}.route-receipt a{margin-left:auto;color:var(--blue);font-weight:800}
.status-strip{display:grid;grid-template-columns:repeat(4,1fr) 1.35fr;margin:22px 0 95px;border:1px solid var(--line);border-radius:15px;background:#fff;box-shadow:0 12px 35px rgba(28,58,91,.06)}.status-strip>div,.status-strip>a{display:flex;flex-direction:column;justify-content:center;min-height:80px;padding:17px 22px;border-right:1px solid var(--line)}.status-strip span{color:#75869a;font-size:10px;font-weight:800;letter-spacing:.09em;text-transform:uppercase}.status-strip b{display:flex;align-items:center;gap:9px;margin-top:5px;font-size:17px}.status-strip>a{align-items:center;flex-direction:row;justify-content:space-between;border:0;color:var(--blue);font-size:13px;font-weight:800}
.operating-system,.workspace-section,.activity-section{margin-top:100px}.section-intro{display:grid;grid-template-columns:1.2fr .8fr;gap:70px;align-items:end;margin-bottom:42px}.section-intro h2{margin:15px 0 0;font-size:clamp(38px,4.6vw,64px);line-height:1;letter-spacing:-.055em}.section-intro>p{max-width:540px;margin:0;color:var(--muted);font-size:16px;line-height:1.7}.section-intro.compact h2{font-size:clamp(34px,4vw,52px)}.section-intro a{justify-self:end;color:var(--blue);font-size:13px;font-weight:800}.system-flow{display:grid;grid-template-columns:repeat(4,1fr);border-top:1px solid #b9c9dc}.system-flow article{position:relative;padding:20px 28px 26px 0}.system-flow article>span{color:#8698aa;font:800 10px inherit}.flow-signal{position:relative;height:42px;margin:13px 0}.flow-signal:before{content:"";position:absolute;left:0;right:0;top:20px;height:1px;background:linear-gradient(90deg,var(--blue),#bdd2f4)}.flow-signal i{position:absolute;left:0;top:16px;width:9px;height:9px;border-radius:50%;background:var(--blue);box-shadow:0 0 0 7px rgba(7,88,238,.1);animation:pulse 2.4s ease-in-out infinite}.system-flow article:nth-child(2) i{animation-delay:.4s}.system-flow article:nth-child(3) i{animation-delay:.8s}.system-flow article:nth-child(4) i{animation-delay:1.2s}.system-flow h3{margin:0 0 10px;font-size:22px}.system-flow p{margin:0;color:var(--muted);font-size:13px;line-height:1.65}
.center-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.center-card{display:flex;flex-direction:column;min-height:330px;padding:25px;border:1px solid var(--line);border-radius:17px;background:linear-gradient(145deg,#fff,#f9fbfe);color:inherit;transition:.25s ease}.center-card:hover{transform:translateY(-5px);border-color:#9bbbf0;box-shadow:0 20px 48px rgba(18,61,112,.12)}.card-top{display:flex;justify-content:space-between;color:#8496a9;font:800 11px inherit}.card-top i{display:grid;place-items:center;width:29px;height:29px;border-radius:50%;background:#edf4ff;color:var(--blue);font-style:normal}.center-card small{margin-top:45px;color:var(--blue);font-size:10px;font-weight:800;letter-spacing:.12em;text-transform:uppercase}.center-card h3{margin:8px 0 12px;font-size:25px;letter-spacing:-.03em}.center-card p{margin:0;color:var(--muted);font-size:13px;line-height:1.65}.action-tags{display:flex;gap:6px;flex-wrap:wrap;margin-top:auto;padding-top:22px}.action-tags span{padding:6px 8px;border-radius:6px;background:#edf3fa;color:#536b82;font-size:9px;font-weight:800}
.activity-list{border-top:1px solid var(--line)}.activity-row{display:grid;grid-template-columns:20px 1fr auto 22px;gap:12px;align-items:center;padding:18px 12px;border-bottom:1px solid var(--line);color:inherit;transition:background .2s}.activity-row:hover{background:#f6f9fd}.state-dot{width:8px;height:8px;border-radius:50%;background:#9baaba}.state-dot.running{background:#2379ff;box-shadow:0 0 0 5px #e1edff}.state-dot.done{background:#25b77a}.state-dot.failed{background:#e25a5a}.activity-row div{display:flex;flex-direction:column;gap:4px}.activity-row b{font-size:13px}.activity-row div span{color:#8492a2;font-size:10px;text-transform:capitalize}.activity-row em{padding:6px 8px;border-radius:99px;background:#eef2f6;color:#637487;font-size:9px;font-style:normal;font-weight:900;text-transform:uppercase}.activity-row em.running{color:#1765ca;background:#e5f0ff}.activity-row em.done{color:#148056;background:#e4f7ee}.activity-row em.failed{color:#a33a3a;background:#feeaea}.activity-row>i{color:var(--blue);font-style:normal}.empty-state{display:flex;align-items:center;gap:20px;padding:38px;border:1px dashed #bdd0e4;border-radius:14px;background:#f8fbff}.empty-state>span{font-size:30px;color:var(--blue)}.empty-state b{font-size:15px}.empty-state p{margin:5px 0 0;color:var(--muted);font-size:12px}.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)}
@keyframes pulse{50%{transform:translateX(16px);box-shadow:0 0 0 12px rgba(7,88,238,0)}}
@media(max-width:1000px){.command-hero{grid-template-columns:1fr;gap:38px;padding:55px 6%}.center-grid{grid-template-columns:repeat(2,1fr)}.system-flow{grid-template-columns:repeat(2,1fr)}.status-strip{grid-template-columns:repeat(4,1fr)}.status-strip>a{grid-column:1/-1;border-top:1px solid var(--line)}.section-intro{grid-template-columns:1fr;gap:22px}}
@media(max-width:700px){.command-page{padding:14px 13px 60px}.command-hero{min-height:0;padding:42px 20px;border-radius:20px}h1{font-size:46px}.hero-copy>p{font-size:15px}.command-composer{padding:17px}.composer-tools{align-items:stretch;flex-direction:column}.send-button{height:46px}.quick-starts button{max-width:100%}.status-strip{grid-template-columns:repeat(2,1fr);margin-bottom:70px}.status-strip>div:nth-child(2){border-right:0}.status-strip>div:nth-child(3),.status-strip>div:nth-child(4){border-top:1px solid var(--line)}.section-intro h2{font-size:40px}.system-flow,.center-grid{grid-template-columns:1fr}.center-card{min-height:290px}.route-receipt{align-items:flex-start;flex-direction:column}.route-receipt a{margin-left:0}}
@media(prefers-reduced-motion:reduce){.flow-signal i{animation:none}.center-card{transition:none}}
</style>
