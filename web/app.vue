<template>
  <LegoraLanding v-if="!user" :signing-in="signingIn" :auth-error="authError" @sign-in="signIn" />
  <template v-else><NuxtLayout><NuxtPage /></NuxtLayout><PreActionGuidance /></template>
  <ExperienceLayer />
</template>

<script setup lang="ts">

const supabase = useSupabaseClient<any>()
const user = useSupabaseUser()
const route = useRoute()
const signingIn = ref(false)
const authError = ref('')
type Admission = { mode: 'member' | 'referral'; grantToken?: string }
async function signIn(admission: Admission = { mode: 'member' }) { signingIn.value = true; authError.value = ''; try { if (import.meta.client) { sessionStorage.setItem('orchestrator:return-to', route.fullPath); if (admission.grantToken) sessionStorage.setItem('madeus:access-grant', admission.grantToken) } const { error } = await supabase.auth.signInWithOAuth({ provider: 'google', options: { redirectTo: import.meta.client ? window.location.origin : undefined } }); if (error) throw error } catch (e: any) { authError.value = e?.message || 'Unable to sign in.'; signingIn.value = false } }
watch(user, async value => {
  if (!value || !import.meta.client) return
  const grantToken = sessionStorage.getItem('madeus:access-grant')
  if (grantToken) {
    try {
      const { data: { session } } = await supabase.auth.getSession()
      await $fetch('/api/public/access/claim', { method: 'POST', body: { grant_token: grantToken }, headers: session?.access_token ? { authorization: `Bearer ${session.access_token}` } : {} })
      sessionStorage.removeItem('madeus:access-grant')
    } catch (error: any) {
      sessionStorage.removeItem('madeus:access-grant')
      authError.value = error?.data?.message || error?.message || 'Your referral grant could not be claimed.'
      await supabase.auth.signOut()
      signingIn.value = false
      return
    }
  }
  try {
    const { data: { session } } = await supabase.auth.getSession()
    await $fetch('/api/public/access/status', { headers: session?.access_token ? { authorization: `Bearer ${session.access_token}` } : {} })
  } catch (error: any) {
    authError.value = error?.data?.message || error?.message || 'A valid Madeus membership is required.'
    await supabase.auth.signOut()
    signingIn.value = false
    return
  }
  const returnTo = sessionStorage.getItem('orchestrator:return-to')
  sessionStorage.removeItem('orchestrator:return-to')
  if (returnTo && returnTo !== route.fullPath) await navigateTo(returnTo)
})
watch(() => [user.value?.id, route.fullPath], async ([id, path]) => {
  if (!id || !import.meta.client) return
  try { await $fetch('/api/product-metric', { method: 'POST', body: { experiment: 'orchestrator_navigation_v1', metric: 'page_view', route: path, subject: path } }) } catch {}
}, { immediate: true })
</script>
