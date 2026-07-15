<script setup lang="ts">
const router = useRouter()
const route = useRoute()
const navigating = ref(false)
const progress = ref(0)
const outcome = ref<{ tone: 'success' | 'error'; title: string; detail: string } | null>(null)
let progressTimer: ReturnType<typeof setInterval> | null = null
let outcomeTimer: ReturnType<typeof setTimeout> | null = null

function clearProgressTimer() {
  if (progressTimer) clearInterval(progressTimer)
  progressTimer = null
}

function begin() {
  navigating.value = true
  progress.value = 12
  clearProgressTimer()
  progressTimer = setInterval(() => { progress.value = Math.min(88, progress.value + Math.max(2, (92 - progress.value) * .12)) }, 110)
}

function finish() {
  clearProgressTimer()
  progress.value = 100
  setTimeout(() => { navigating.value = false; progress.value = 0 }, 260)
}

function announce(event: Event) {
  const detail = (event as CustomEvent).detail || {}
  outcome.value = {
    tone: detail.tone === 'error' ? 'error' : 'success',
    title: detail.title || (detail.tone === 'error' ? 'Action needs attention' : 'Outcome confirmed'),
    detail: detail.detail || (detail.tone === 'error' ? 'Review the evidence and retry.' : 'The requested action completed successfully.'),
  }
  if (outcomeTimer) clearTimeout(outcomeTimer)
  outcomeTimer = setTimeout(() => { outcome.value = null }, 5200)
}

onMounted(() => {
  router.beforeEach(() => begin())
  router.afterEach(() => finish())
  window.addEventListener('madeus:outcome', announce)
})
onUnmounted(() => {
  clearProgressTimer()
  if (outcomeTimer) clearTimeout(outcomeTimer)
  if (import.meta.client) window.removeEventListener('madeus:outcome', announce)
})
watch(() => route.fullPath, () => { if (navigating.value) finish() })
</script>

<template>
  <div class="experience-layer" aria-live="polite">
    <div class="route-progress" :class="{ active: navigating }" :style="{ '--progress': `${progress}%` }"><i /></div>
    <Transition name="outcome">
      <aside v-if="outcome" class="outcome-signal" :class="outcome.tone" role="status">
        <span class="outcome-icon">{{ outcome.tone === 'success' ? '✓' : '!' }}</span>
        <span><b>{{ outcome.title }}</b><small>{{ outcome.detail }}</small></span>
        <button aria-label="Dismiss acknowledgement" @click="outcome = null">×</button>
      </aside>
    </Transition>
  </div>
</template>

<style scoped>
.experience-layer{position:fixed;z-index:220;inset:0;pointer-events:none}.route-progress{position:absolute;top:0;left:0;width:100%;height:2px;opacity:0;transition:opacity .18s}.route-progress.active{opacity:1}.route-progress i{display:block;width:var(--progress);height:100%;background:linear-gradient(90deg,#111,#635bff,#4fc98b);box-shadow:0 0 18px #635bff80;transition:width .16s ease}.outcome-signal{position:absolute;right:22px;bottom:22px;display:grid;grid-template-columns:32px minmax(0,1fr) 20px;gap:11px;align-items:center;width:min(380px,calc(100vw - 32px));border:1px solid #d7ded9;border-radius:14px;padding:13px;background:#fffffff2;box-shadow:0 22px 70px #1112;backdrop-filter:blur(18px);pointer-events:auto}.outcome-signal.error{border-color:#efd0cb}.outcome-icon{display:grid;width:32px;height:32px;place-items:center;border-radius:50%;background:#eaf8f0;color:#247649;font-weight:750}.error .outcome-icon{background:#fff0ee;color:#b42318}.outcome-signal b,.outcome-signal small{display:block}.outcome-signal b{font-size:11px}.outcome-signal small{margin-top:4px;color:#777;font-size:9px;line-height:1.4}.outcome-signal button{border:0;background:transparent;color:#aaa;cursor:pointer}.outcome-enter-active,.outcome-leave-active{transition:.28s cubic-bezier(.2,.8,.2,1)}.outcome-enter-from,.outcome-leave-to{opacity:0;transform:translateY(12px) scale(.97)}
</style>
