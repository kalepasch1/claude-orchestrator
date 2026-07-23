<template>
  <main v-if="authResolving" class="auth-return" aria-live="polite">
    <div class="auth-return__mark">M</div>
    <p>Securing your Madeus workspace…</p>
  </main>
  <LegoraLanding v-else-if="!user" :signing-in="signingIn" :auth-error="authError" @sign-in="signIn" />
  <template v-else>
    <NuxtLayout><NuxtPage /></NuxtLayout>
    <PreActionGuidance />
  </template>
  <ExperienceLayer />
</template>

<script setup lang="ts">
import { authCallbackUrl, normalizeAuthReturnTo } from '~/utils/authRedirect'

const supabase = useSupabaseClient<any>()
const user = useSupabaseUser()
const route = useRoute()
const signingIn = ref(false)
const authError = ref('')
const authResolving = ref(import.meta.client && route.path === '/auth/callback')
const admissionRunning = ref(false)

type Admission = { mode: 'member' | 'referral'; grantToken?: string }

async function signIn(admission: Admission = { mode: 'member' }) {
  signingIn.value = true
  authError.value = ''
  try {
    const returnTo = normalizeAuthReturnTo(route.fullPath)
    if (import.meta.client) {
      sessionStorage.setItem('orchestrator:return-to', returnTo)
      if (admission.grantToken) sessionStorage.setItem('madeus:access-grant', admission.grantToken)
    }
    const { error } = await supabase.auth.signInWithOAuth({
      provider: 'google',
      options: { redirectTo: import.meta.client ? authCallbackUrl(window.location.origin) : undefined },
    })
    if (error) throw error
  } catch (cause: any) {
    authError.value = cause?.message || 'Unable to sign in.'
    signingIn.value = false
  }
}

async function admitAndRoute() {
  if (!import.meta.client || admissionRunning.value || !user.value) return
  admissionRunning.value = true
  authResolving.value = true
  try {
    const { data: { session } } = await supabase.auth.getSession()
    if (!session?.access_token) throw new Error('Authenticated session could not be restored.')

    const grantToken = sessionStorage.getItem('madeus:access-grant')
    if (grantToken) {
      await $fetch('/api/public/access/claim', {
        method: 'POST',
        body: { grant_token: grantToken },
        headers: { authorization: `Bearer ${session.access_token}` },
      })
      sessionStorage.removeItem('madeus:access-grant')
    }

    await $fetch('/api/public/access/status', {
      headers: { authorization: `Bearer ${session.access_token}` },
    })

    const storedReturn = sessionStorage.getItem('orchestrator:return-to')
    const returnTo = normalizeAuthReturnTo(storedReturn || route.fullPath)
    sessionStorage.removeItem('orchestrator:return-to')
    await navigateTo(returnTo, { replace: true })
  } catch (cause: any) {
    sessionStorage.removeItem('madeus:access-grant')
    authError.value = cause?.data?.message || cause?.message || 'A valid Madeus membership is required.'
    await supabase.auth.signOut()
    if (route.path === '/auth/callback') await navigateTo('/', { replace: true })
  } finally {
    admissionRunning.value = false
    signingIn.value = false
    authResolving.value = false
  }
}

async function completeOAuthCallback() {
  if (!import.meta.client || route.path !== '/auth/callback') return
  authResolving.value = true
  authError.value = ''
  try {
    const callbackError = typeof route.query.error_description === 'string'
      ? route.query.error_description
      : typeof route.query.error === 'string' ? route.query.error : ''
    if (callbackError) throw new Error(callbackError)

    let { data: { session } } = await supabase.auth.getSession()
    const code = typeof route.query.code === 'string' ? route.query.code : ''
    if (!session && code) {
      const result = await supabase.auth.exchangeCodeForSession(code)
      if (result.error) throw result.error
      session = result.data.session
    }
    if (!session) throw new Error('Google sign-in completed without a Madeus session. Please try again.')
    await admitAndRoute()
  } catch (cause: any) {
    authError.value = cause?.message || 'Unable to complete sign in.'
    signingIn.value = false
    authResolving.value = false
    await navigateTo('/', { replace: true })
  }
}

onMounted(async () => {
  if (route.path === '/auth/callback') await completeOAuthCallback()
  else if (user.value) await admitAndRoute()
})

watch(user, async value => {
  if (value) await admitAndRoute()
})

watch(() => [user.value?.id, route.fullPath], async ([id, path]) => {
  if (!id || !import.meta.client) return
  try {
    await $fetch('/api/product-metric', {
      method: 'POST',
      body: { experiment: 'orchestrator_navigation_v1', metric: 'page_view', route: path, subject: path },
    })
  } catch {}
}, { immediate: true })
</script>

<style>
.auth-return{min-height:100svh;display:grid;place-content:center;justify-items:center;gap:22px;background:#0b0c0b;color:#fff;font-family:Inter,Arial,sans-serif}.auth-return__mark{display:grid;width:78px;height:78px;place-items:center;border:1px solid #ffffff38;background:#ffffff09;font-size:28px}.auth-return p{margin:0;color:#c5c7c0;font:11px ui-monospace,monospace;letter-spacing:.12em;text-transform:uppercase}
</style>
