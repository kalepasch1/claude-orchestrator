// Nuxt config - hosted control plane (deploys to Vercel out of the box).
export default defineNuxtConfig({
  modules: ['@nuxtjs/supabase', '@nuxtjs/tailwindcss'],
  ssr: true,
  // SUPABASE_URL + SUPABASE_KEY (anon) come from env vars on Vercel.
  supabase: {
    // we gate auth inside index.vue, so don't force a global redirect
    redirect: false
  },
  css: ['~/assets/main.css'],
  app: {
    head: {
      title: 'Claude Orchestrator',
      meta: [{ name: 'viewport', content: 'width=device-width, initial-scale=1' }]
    }
  }
})
