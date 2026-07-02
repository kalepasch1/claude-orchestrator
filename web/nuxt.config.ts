// Nuxt config - hosted control plane (deploys to Vercel out of the box).
export default defineNuxtConfig({
  modules: ['@nuxtjs/supabase', '@nuxtjs/tailwindcss'],
  ssr: true,
  // The kernel ships raw ESM/TS (zero deps) — let Vite transpile it in the bundle.
  build: { transpile: ['@darwin/kernel'] },
  vite: { ssr: { noExternal: ['@darwin/kernel'] } },
  // SUPABASE_URL + SUPABASE_KEY (anon) come from env vars on Vercel.
  supabase: {
    // we gate auth inside index.vue, so don't force a global redirect
    redirect: false
  },
  css: ['~/assets/main.css'],
  app: {
    head: {
      title: 'Claude Orchestrator',
      meta: [{ name: 'viewport', content: 'width=device-width, initial-scale=1' }],
      link: [
        { rel: 'preconnect', href: 'https://fonts.googleapis.com' },
        { rel: 'preconnect', href: 'https://fonts.gstatic.com', crossorigin: '' },
        {
          rel: 'stylesheet',
          href: 'https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&display=swap'
        }
      ]
    }
  }
})
