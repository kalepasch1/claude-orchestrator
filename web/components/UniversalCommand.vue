<script setup lang="ts">
import { CAPABILITY_DESTINATIONS } from '~/config/orchestratorCapabilities'

type Attachment = { name: string; type: string; size: number; base64: string; text?: string }
const supabase = useSupabaseClient<any>()
const route = useRoute()
const { track } = useExperienceTelemetry('universal-command')
const open = ref(false)
const command = ref('')
const loading = ref(false)
const result = ref<any>(null)
const contextResult = ref<any>(null)
const attachments = ref<Attachment[]>([])
const error = ref('')
const activeIndex = ref(0)
const openedAt = ref(0)
const listening = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

const destinations = [
  { label: 'What should we accomplish?', description: 'Route any outcome automatically', to: '/orchestrators', keywords: ['start', 'command', 'autopilot'] },
  { label: 'Connections', description: 'Connect specialist tools and accounts', to: '/connectors', keywords: ['apps', 'tools', 'vendors', 'figma', 'adobe'] },
  { label: 'Sign-offs', description: 'Review decisions that require you', to: '/sign-offs', keywords: ['approval', 'review', 'decision'] },
  { label: 'Portfolio activity', description: 'See work in progress and evidence', to: '/queue', keywords: ['tasks', 'history', 'proof'] },
  ...CAPABILITY_DESTINATIONS,
]
const suggestions = computed(() => {
  const terms = command.value.trim().toLowerCase().split(/\s+/).filter(Boolean)
  if (!terms.length) return destinations.slice(0, 7)
  return destinations.map(item => ({ ...item, score: terms.reduce((score, term) => score + (`${item.label} ${item.description} ${item.keywords.join(' ')}`.toLowerCase().includes(term) ? 1 : 0), 0) }))
    .filter(item => item.score).sort((a, b) => b.score - a.score).slice(0, 7)
})
const richOutcome = computed(() => attachments.value.length > 0 || command.value.trim().split(/\s+/).length > 3)

function authHeaders(token?: string): Record<string, string> { return token ? { authorization: `Bearer ${token}` } : {} }
function show() { open.value = true; openedAt.value = Date.now(); activeIndex.value = 0; track('action_started', { trigger: 'palette_open', route: route.path }) }
function clear() { command.value = ''; attachments.value = []; contextResult.value = null; result.value = null }
function close(reason = 'dismissed') { if (open.value) track('guidance_dismissed', { reason, dwell_ms: Date.now() - openedAt.value, query_length: command.value.length, attachment_count: attachments.value.length }); open.value = false; result.value = null; error.value = '' }

async function filePayload(file: File): Promise<Attachment> {
  const base64 = await new Promise<string>((resolve, reject) => { const reader = new FileReader(); reader.onerror = () => reject(reader.error); reader.onload = () => resolve(String(reader.result).split(',')[1] || ''); reader.readAsDataURL(file) })
  const textual = /^(text\/|application\/json)/.test(file.type)
  return { name: file.name, type: file.type || 'text/plain', size: file.size, base64, text: textual ? (await file.text()).slice(0, 50_000) : undefined }
}
async function addFiles(event: Event) {
  error.value = ''
  try {
    const files = Array.from((event.target as HTMLInputElement).files || [])
    if (attachments.value.length + files.length > 5) throw new Error('Attach up to five files at a time.')
    if (files.some(file => file.size > 8 * 1024 * 1024)) throw new Error('Each attachment must be under 8 MB.')
    attachments.value.push(...await Promise.all(files.map(filePayload)))
    track('action_started', { trigger: 'multimodal_context', attachment_count: attachments.value.length })
  } catch (e: any) { error.value = e.message || 'Could not read that attachment.' }
  finally { if (fileInput.value) fileInput.value.value = '' }
}
function removeAttachment(index: number) { attachments.value.splice(index, 1); contextResult.value = null }
function dictate() {
  const Recognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
  if (!Recognition) { error.value = 'Voice input is not supported by this browser.'; return }
  const recognition = new Recognition(); recognition.continuous = false; recognition.interimResults = false; recognition.lang = navigator.language || 'en-US'; listening.value = true
  recognition.onresult = (event: any) => { const transcript = event.results?.[0]?.[0]?.transcript || ''; command.value = [command.value, transcript].filter(Boolean).join(' '); track('action_started', { trigger: 'voice_context' }) }
  recognition.onerror = () => { error.value = 'Voice input stopped before a result was captured.' }
  recognition.onend = () => { listening.value = false }
  recognition.start()
}
async function persistContext(token?: string) {
  if (contextResult.value || !attachments.value.length) return contextResult.value
  contextResult.value = await $fetch('/api/command/context', { method: 'POST', body: { command: command.value, files: attachments.value }, headers: authHeaders(token) })
  return contextResult.value
}
function pendingIntent() {
  const refs = (contextResult.value?.attachments || []).map((item: any) => `${item.name}${item.url ? `: ${item.url}` : ''}${item.text ? `\nExtracted content:\n${item.text}` : ''}`).join('\n')
  return [command.value.trim(), contextResult.value?.reference, refs && `Attached context (private signed links expire automatically):\n${refs}`].filter(Boolean).join('\n\n')
}
function rememberPending() { if (import.meta.client && (command.value.trim() || contextResult.value)) sessionStorage.setItem('madeus:pending-command', JSON.stringify({ intent: pendingIntent(), context_id: contextResult.value?.id || null, created_at: Date.now() })) }
async function choose(item: typeof destinations[number]) {
  loading.value = true; error.value = ''
  try { const { data: { session } } = await supabase.auth.getSession(); await persistContext(session?.access_token); rememberPending(); track('action_completed', { trigger: 'instant_destination', destination: item.to, attachment_count: attachments.value.length }); close('navigated'); clear(); await navigateTo(item.to) }
  catch (e: any) { error.value = e?.data?.message || e?.message || 'Madeus could not preserve this command context.' }
  finally { loading.value = false }
}
async function run() {
  if (!command.value.trim() && !attachments.value.length) return
  if (!richOutcome.value && suggestions.value[activeIndex.value]) return choose(suggestions.value[activeIndex.value])
  loading.value = true; error.value = ''
  try {
    const { data: { session } } = await supabase.auth.getSession(); await persistContext(session?.access_token)
    const response: any = await $fetch('/api/constitution/action', { method: 'POST', body: { action: 'command', values: { command: pendingIntent() } }, headers: authHeaders(session?.access_token) })
    result.value = response.command; track('guidance_followed', { trigger: 'governed_resolution', capability: result.value?.capability, attachment_count: attachments.value.length })
  } catch (e: any) { error.value = e?.data?.message || e?.message || 'Madeus could not resolve this command.' }
  finally { loading.value = false }
}
async function go() { if (!result.value?.destination) return; const destination = result.value.destination; rememberPending(); track('action_completed', { trigger: 'governed_destination', destination, capability: result.value.capability }); close('navigated'); clear(); await navigateTo(destination) }
function keys(event: KeyboardEvent) { if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); open.value ? close() : show(); return } if (!open.value) return; if (event.key === 'Escape') close(); if (event.key === 'ArrowDown') { event.preventDefault(); activeIndex.value = Math.min(activeIndex.value + 1, suggestions.value.length - 1) }; if (event.key === 'ArrowUp') { event.preventDefault(); activeIndex.value = Math.max(activeIndex.value - 1, 0) } }
watch(command, () => { activeIndex.value = 0; result.value = null; contextResult.value = null })
onMounted(() => window.addEventListener('keydown', keys)); onUnmounted(() => window.removeEventListener('keydown', keys))
</script>

<template>
  <button type="button" class="command-trigger" aria-label="Open universal command" aria-haspopup="dialog" :aria-expanded="open" @click="show"><span>⌘K</span> Command</button>
  <div v-if="open" class="command-backdrop" role="dialog" aria-modal="true" aria-label="Universal capability command" @mousedown.self="close()">
    <section class="command-dialog">
      <header><div><span>Universal capability command</span><h2>Describe the outcome. Add anything useful.</h2></div><button type="button" aria-label="Close universal command" @click="close()">×</button></header>
      <form class="command-input" @submit.prevent="run"><span>⌕</span><input v-model="command" autofocus aria-label="Search capabilities or describe an outcome" placeholder="Build, fix, research, review, or improve anything…"><button type="button" title="Attach screenshot, document, data, audio, or video" @click="fileInput?.click()">＋</button><button type="button" :class="{ listening }" title="Dictate outcome" @click="dictate">{{ listening ? '●' : '◉' }}</button><kbd>↵</kbd><input ref="fileInput" class="sr-only" type="file" multiple accept="image/png,image/jpeg,image/webp,image/gif,application/pdf,text/plain,text/csv,application/json,text/markdown,audio/webm,audio/mpeg,audio/mp4,video/mp4,video/webm" @change="addFiles"></form>
      <div v-if="attachments.length" class="attachment-row"><span v-for="(file,index) in attachments" :key="`${file.name}:${index}`"><b>{{ file.name }}</b><small>{{ (file.size/1024/1024).toFixed(1) }} MB</small><button type="button" :aria-label="`Remove ${file.name}`" @click="removeAttachment(index)">×</button></span></div>
      <div v-if="suggestions.length && !richOutcome" class="command-results"><button v-for="(item, index) in suggestions" :key="`${item.to}:${item.label}`" type="button" :class="{ active: index === activeIndex }" @mouseenter="activeIndex = index" @click="choose(item)"><span><b>{{ item.label }}</b><small>{{ item.description }}</small></span><i>↗</i></button></div>
      <div v-else-if="!result" class="command-resolve"><p>Madeus preserves attached context, identifies the workspace, then chooses research depth, specialists, providers, models, worktrees, verification, and release policy.</p><button :disabled="loading" @click="run">{{ loading ? 'Preserving + routing…' : 'Route this outcome' }} →</button></div>
      <p v-if="error" class="command-error">{{ error }}</p>
      <article v-if="result" class="command-proof"><span>{{ result.capability }} → {{ result.destination }}</span><h3>{{ result.explanation.why }}</h3><p>Least privilege: {{ result.explanation.scopes.join(', ') }} · proof {{ result.proof.digest.slice(0, 12) }}… · {{ result.proof.status }}<template v-if="contextResult"> · context preserved</template></p><div><button type="button" @click="result = null">Revise</button><button type="button" @click="go">Continue with this outcome</button></div></article>
      <footer><span>↑↓ Navigate</span><span>↵ Route</span><span>Esc Close</span><b>Context is private · routing remains automatic</b></footer>
    </section>
  </div>
</template>

<style scoped>
.command-trigger{position:fixed;right:18px;bottom:18px;z-index:40;border:1px solid #d7ddd8;border-radius:99px;padding:9px 13px;background:#fff;box-shadow:0 12px 38px #173b2918;color:#4f5b53;font-size:10px}.command-trigger span{margin-right:6px;color:#194c36;font-weight:750}.command-backdrop{position:fixed;inset:0;z-index:150;padding:11vh 18px 18px;background:#14271d66;backdrop-filter:blur(6px)}.command-dialog{width:min(720px,100%);margin:auto;overflow:hidden;border:1px solid #d6ddd8;border-radius:18px;background:#fff;box-shadow:0 35px 100px #112d2040}.command-dialog>header{display:flex;justify-content:space-between;align-items:start;padding:20px 20px 14px}.command-dialog header span{font-size:9px;font-weight:750;letter-spacing:.15em;text-transform:uppercase;color:#194c36}.command-dialog h2{margin-top:4px;font-size:17px;letter-spacing:-.025em}.command-dialog header button{border:0;background:none;color:#777;font-size:18px}.command-input{display:grid;grid-template-columns:auto 1fr auto auto auto;gap:8px;align-items:center;margin:0 14px;padding:10px 12px;border:1px solid #bdcec2;border-radius:11px;box-shadow:0 0 0 3px #edf3ee}.command-input input{min-width:0;border:0;outline:0;font-size:14px}.command-input>button{display:grid;width:27px;height:27px;place-items:center;border:0;border-radius:7px;background:#f2f5f2;color:#194c36}.command-input>button.listening{background:#194c36;color:#fff}.command-input kbd{border:1px solid #ddd;border-radius:5px;padding:2px 5px;background:#f6f6f3;color:#777;font-size:9px}.sr-only{position:absolute!important;width:1px!important;height:1px!important;overflow:hidden!important;clip:rect(0,0,0,0)!important}.attachment-row{display:flex;gap:6px;overflow-x:auto;padding:10px 14px 0}.attachment-row>span{display:flex;align-items:center;gap:6px;border:1px solid #d8e2da;border-radius:8px;padding:6px 7px;background:#f5f8f5;white-space:nowrap}.attachment-row b{max-width:130px;overflow:hidden;text-overflow:ellipsis;font-size:9px}.attachment-row small{color:#7c857f;font-size:8px}.attachment-row button{border:0;background:none;color:#6b756e}.command-results{display:grid;gap:2px;padding:10px 14px}.command-results button{display:flex;justify-content:space-between;align-items:center;border:0;border-radius:9px;padding:10px;background:#fff;text-align:left}.command-results button.active{background:#edf3ee}.command-results b,.command-results small{display:block}.command-results b{font-size:11px}.command-results small{margin-top:3px;color:#7b827d;font-size:9px}.command-results i{color:#194c36;font-style:normal}.command-resolve{display:flex;justify-content:space-between;gap:20px;align-items:center;margin:10px 14px;padding:14px;border-radius:10px;background:#edf3ee}.command-resolve p{max-width:490px;font-size:10px;line-height:1.55;color:#536158}.command-resolve button,.command-proof div button:last-child{border:0;border-radius:8px;padding:9px 12px;background:#194c36;color:#fff;font-size:10px;white-space:nowrap}.command-error{margin:8px 18px;color:#a33;font-size:10px}.command-proof{margin:10px 14px;padding:15px;border:1px solid #bfd2c4;border-radius:11px;background:#f2f7f3}.command-proof>span{font-size:9px;font-weight:700;color:#194c36}.command-proof h3{margin-top:5px;font-size:12px}.command-proof p{margin-top:5px;font-size:9px;color:#68716b}.command-proof div{display:flex;justify-content:flex-end;gap:7px;margin-top:12px}.command-proof div button{border:1px solid #d4d8d5;border-radius:8px;padding:8px 11px;background:#fff;font-size:9px}.command-dialog>footer{display:flex;gap:14px;align-items:center;padding:10px 18px;border-top:1px solid #e6e8e4;background:#fafbf9;color:#8a908c;font-size:8px}.command-dialog footer b{margin-left:auto;color:#55705f}@media(max-width:600px){.command-backdrop{padding:6vh 10px 10px}.command-resolve{align-items:flex-start;flex-direction:column}.command-dialog>footer b{display:none}.command-input{grid-template-columns:auto minmax(0,1fr) auto auto}.command-input kbd{display:none}}
</style>
