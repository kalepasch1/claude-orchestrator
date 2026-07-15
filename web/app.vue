<template>
  <div v-if="!user" class="auth-page"><div class="auth-card"><div class="brand-glyph">M</div><div class="eyebrow">Madeus Orchestrator</div><h1>Turn intent into shipped work.</h1><p>One command surface for research, design, engineering, verification, and release.</p><div v-if="authError" class="inline-error">{{ authError }}</div><button :disabled="signingIn" class="primary-button" @click="signIn">{{ signingIn ? 'Opening workspace…' : 'Continue with Google' }} <span>↗</span></button><small>Your identity controls organization access and delegated capabilities.</small></div><div class="auth-aside"><span>Outcome-first orchestration</span><blockquote>“Describe the result. Madeus assembles and governs the path.”</blockquote><div><b>Adaptive routing</b><b>Independent QA</b><b>Verified release</b></div></div></div>
  <template v-else><NuxtLayout><NuxtPage /></NuxtLayout><PreActionGuidance /></template>
</template>

<script setup lang="ts">
// @vercel/analytics is enabled as a Nuxt module in nuxt.config.ts ('@vercel/analytics/nuxt'),
// which auto-injects tracking. Importing its module entry here pulled @nuxt/kit into the Vue
// app and failed the build (nuxt:import-protection).
const supabase = useSupabaseClient<any>()
const user = useSupabaseUser()
const route = useRoute()
const signingIn = ref(false)
const authError = ref('')
async function signIn() { signingIn.value = true; authError.value = ''; try { if (import.meta.client) sessionStorage.setItem('orchestrator:return-to', route.fullPath); const { error } = await supabase.auth.signInWithOAuth({ provider: 'google', options: { redirectTo: import.meta.client ? window.location.origin : undefined } }); if (error) throw error } catch (e: any) { authError.value = e?.message || 'Unable to sign in.'; signingIn.value = false } }
watch(user, async value => { if (!value || !import.meta.client) return; const returnTo = sessionStorage.getItem('orchestrator:return-to'); sessionStorage.removeItem('orchestrator:return-to'); if (returnTo && returnTo !== route.fullPath) await navigateTo(returnTo) })
watch(() => [user.value?.id, route.fullPath], async ([id, path]) => {
  if (!id || !import.meta.client) return
  try { await $fetch('/api/product-metric', { method: 'POST', body: { experiment: 'orchestrator_navigation_v1', metric: 'page_view', route: path, subject: path } }) } catch {}
}, { immediate: true })
</script>
