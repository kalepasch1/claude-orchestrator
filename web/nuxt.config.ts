import { fileURLToPath } from 'node:url'

const kernel = (path: string) =>
  fileURLToPath(new URL(`../packages/darwin-kernel/src/${path}`, import.meta.url))

const kernelAlias = {
  '@darwin/kernel': kernel('index.ts'),
  '@darwin/kernel/fleetAdmin': kernel('fleetAdmin/index.ts'),
  '@darwin/kernel/governance': kernel('governance/index.ts')
}

const appAlias = {
  ...kernelAlias,
  cookie: fileURLToPath(new URL('./utils/cookie-compat.ts', import.meta.url))
}

// Nuxt config - hosted control plane (deploys to Vercel out of the box).
export default defineNuxtConfig({
  modules: ['@nuxtjs/supabase', '@nuxtjs/tailwindcss', '@vercel/analytics/nuxt'],
  ssr: true,
  experimental: { appManifest: false },
  alias: appAlias,
  // The kernel ships raw ESM/TS (zero deps) — let Vite transpile it in the bundle.
  build: { transpile: ['@darwin/kernel'] },
  vite: {
    resolve: { alias: appAlias },
    ssr: { noExternal: ['@darwin/kernel'] }
  },
  nitro: { alias: appAlias },
  // SUPABASE_URL + SUPABASE_KEY (anon) come from env vars on Vercel.
  supabase: {
    // we gate auth inside index.vue, so don't force a global redirect
    redirect: false,
    // OAuth is completed explicitly in app.vue so the landing page cannot win
    // a race against automatic PKCE exchange and render after a valid callback.
    clientOptions: { auth: { flowType: 'pkce', detectSessionInUrl: false } }
  },
  routeRules: {
    // The PKCE verifier lives in the browser; keep the callback entirely
    // client-rendered so no unauthenticated landing state can flash first.
    '/auth/callback': { ssr: false }
  },
  css: ['~/assets/main.css'],
  app: {
    pageTransition: { name: 'page', mode: 'out-in' },
    layoutTransition: { name: 'layout', mode: 'out-in' },
    head: {
      htmlAttrs: { lang: 'en' },
      // Kept in sync with components/LegoraLanding.vue, which is the public surface.
      title: 'Madeus — The private operating system for company building',
      meta: [
        { name: 'viewport', content: 'width=device-width, initial-scale=1' },
        { name: 'theme-color', content: '#0b0c0b' },
        { name: 'format-detection', content: 'telephone=no' },
        {
          name: 'description',
          content:
            'Madeus is the private operating system for founders running multiple companies — private intelligence, governed execution, and independently verified outcomes. By invitation.'
        },
        { name: 'author', content: 'Madeus' },
        { property: 'og:site_name', content: 'Madeus' },
        { property: 'og:locale', content: 'en_US' }
      ],
      link: [
        { rel: 'icon', type: 'image/svg+xml', href: '/madeus-mark.svg' },
        { rel: 'apple-touch-icon', href: '/madeus-mark.svg' },
        { rel: 'preconnect', href: 'https://fonts.googleapis.com' },
        { rel: 'preconnect', href: 'https://fonts.gstatic.com', crossorigin: '' },
        {
          rel: 'stylesheet',
          href: 'https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Inter:wght@400;500;600;700&family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600&display=swap'
        }
      ]
    }
  }
})
